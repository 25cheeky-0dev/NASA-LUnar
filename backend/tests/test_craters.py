import sqlite3
import pytest
from app.regions import craters

@pytest.fixture
def catalogue(tmp_path,monkeypatch):
 p=tmp_path/'test.sqlite'
 with sqlite3.connect(p) as db:
  db.executescript('CREATE TABLE craters(rid INTEGER PRIMARY KEY,id TEXT,lon REAL,lat REAL,diameter_km REAL);CREATE VIRTUAL TABLE locations USING rtree(rid,minx,maxx,miny,maxy);')
  values=[(0,0,2),(.08,.08,3),(359.98,.02,1),(.5,0,100),(0,0,.9),(179.99,0,1),(180.01,0,2),(290,89.9,2),(5,89.9,2)]
  for i,(lon,lat,d) in enumerate(values):
   db.execute('INSERT INTO craters VALUES(?,?,?,?,?)',(i,str(i),lon,lat,d));db.execute('INSERT INTO locations VALUES(?,?,?,?,?)',(i,lon,lon,lat,lat))
 monkeypatch.setattr(craters,'source',lambda:dict(path=str(p),limitations=['synthetic only'],source_id='SYNTHETIC_ONLY'))

def region(rings):return {'geometry':{'type':'Polygon','coordinates':rings}}

def test_centre_count_threshold_and_holes(catalogue):
 ring=[[-.1,-.1],[.1,-.1],[.1,.1],[-.1,.1],[-.1,-.1]]
 assert craters.count(region([ring]))['count']==3
 hole=[[-.01,-.01],[.01,-.01],[.01,.01],[-.01,.01],[-.01,-.01]]
 result=craters.count(region([ring,hole]));assert result['count']==2
 assert result['largest_diameter_km']==3
 # The 100 km crater whose centre lies outside is deliberately not counted.
 assert all(c['diameter_km']<100 for c in result['largest_catalogued_craters'])

def test_antimeridian_and_pole(catalogue):
 assert craters.count(region([[[179.9,-.1],[180.1,-.1],[180.1,.1],[179.9,.1],[179.9,-.1]]]))['count']==2
 assert craters.count(region([[[-135,89],[-45,89],[45,89],[135,89],[-135,89]]]))['count']==2

def test_missing_catalogue_is_unknown(monkeypatch):
 monkeypatch.setattr(craters,'source',lambda:None)
 result=craters.count({});assert result['status']=='INSUFFICIENT_DATA' and 'count' not in result
