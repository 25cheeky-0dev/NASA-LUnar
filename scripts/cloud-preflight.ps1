param([string]$ProjectId)
$ErrorActionPreference = 'Stop'
$account = gcloud auth list --filter=status:ACTIVE --format='value(account)'
if (-not $account) { throw 'Run gcloud auth login using the project owner account; do not paste credentials into chat.' }
if (-not $ProjectId) { $ProjectId = gcloud config get-value project }
if (-not $ProjectId -or $ProjectId -eq '(unset)') { throw 'Select your project: gcloud config set project YOUR_PROJECT_ID' }
gcloud projects describe $ProjectId --format='table(projectId,name,projectNumber)'
if ($LASTEXITCODE -ne 0) { throw 'Project access failed' }
$billing = gcloud billing projects describe $ProjectId --format=json | ConvertFrom-Json
if (-not $billing.billingEnabled) { throw 'Enable billing for this project before deployment.' }
Write-Output "Authenticated account: $account"
Write-Output "Billing account: $($billing.billingAccountName)"
Write-Output 'Approved budget: USD25/month. Budget alerts are not a hard spending cap.'
Write-Output 'No resources have been provisioned by this preflight.'
