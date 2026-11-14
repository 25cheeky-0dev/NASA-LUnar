param([Parameter(Mandatory=$true)][string]$ProjectId,
      [Parameter(Mandatory=$true)][string]$BillingAccount,
      [ValidateSet('dev','prod')][string]$Environment='dev',
      [string]$Region='us-central1')
$ErrorActionPreference='Stop'
$repo=Split-Path $PSScriptRoot -Parent
& "$PSScriptRoot/cloud-preflight.ps1" -ProjectId $ProjectId
if ($LASTEXITCODE -ne 0) { throw 'Preflight failed' }
$account=gcloud auth list --filter=status:ACTIVE --format='value(account)'
$revision=git -C $repo rev-parse --short HEAD
$image="$Region-docker.pkg.dev/$ProjectId/wispr-$Environment/app:$revision"
$env:TF_VAR_project_id=$ProjectId
$env:TF_VAR_billing_account=$BillingAccount
$env:TF_VAR_invoker_email=$account
$env:TF_VAR_environment=$Environment
$env:TF_VAR_region=$Region
$env:TF_VAR_image=$image
Push-Location "$repo/infra"
try {
 terraform init
 if ($LASTEXITCODE -ne 0) { throw 'Terraform init failed' }
 terraform workspace select -or-create $Environment
 # Bootstrap only bounded supporting resources; do not attempt an absent image.
 terraform plan -target=google_project_service.api -target=google_artifact_registry_repository.images -target=google_service_account.builder -target=google_project_iam_member.builder_logs -target=google_artifact_registry_repository_iam_member.builder -target=google_storage_bucket.build -target=google_storage_bucket_iam_member.build_read -target=google_billing_budget.monthly -out=bootstrap.plan
 if ($LASTEXITCODE -ne 0) { throw 'Bootstrap planning failed' }
 terraform apply bootstrap.plan
 if ($LASTEXITCODE -ne 0) { throw 'Bootstrap failed' }
 $builder=terraform output -raw builder_service_account
 gcloud builds submit $repo --project=$ProjectId --region=$Region --config="$repo/infra/cloudbuild.yaml" --substitutions="_IMAGE=$image" --service-account="projects/$ProjectId/serviceAccounts/$builder" --gcs-source-staging-dir="gs://$ProjectId-wispr-$Environment-build/source"
 if ($LASTEXITCODE -ne 0) { throw 'Container build failed' }
 terraform plan -out=release.plan
 if ($LASTEXITCODE -ne 0) { throw 'Release planning failed' }
 terraform apply release.plan
 if ($LASTEXITCODE -ne 0) { throw 'Release provisioning failed' }
 $bucket=terraform output -raw science_bucket
 gcloud storage rsync "$repo/backend/data/lunar-v1" "gs://$bucket/lunar-v1" --recursive --project=$ProjectId
 if ($LASTEXITCODE -ne 0) { throw 'Scientific asset upload failed' }
 $url=terraform output -raw service_url
 $token=gcloud auth print-identity-token
 $headers=@{Authorization="Bearer $token"}
 Invoke-RestMethod "$url/health" -Headers $headers
 $demo=Invoke-RestMethod "$url/api/v1/explorer/demo" -Headers $headers -Method Post
 $saved=Invoke-RestMethod "$url$($demo.report_url)" -Headers $headers
 if ($saved.result.outcome -ne 'KEEP') { throw 'Recorded demonstration failed' }
 Write-Output "Verified authenticated deployment: $url"
 Write-Output "Open with: gcloud run services proxy wispr-$Environment --project=$ProjectId --region=$Region"
} finally { Pop-Location }
