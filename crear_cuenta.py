from __future__ import annotations
import argparse, base64, hashlib, os
from pathlib import Path
import requests
from dotenv import load_dotenv
load_dotenv(Path(__file__).with_name('.env'))

def hash_password(password: str) -> str:
    salt=os.urandom(16); digest=hashlib.scrypt(password.encode(),salt=salt,n=16384,r=8,p=1)
    return 'scrypt$16384$8$1$'+base64.urlsafe_b64encode(salt).decode()+'$'+base64.urlsafe_b64encode(digest).decode()

def main():
    p=argparse.ArgumentParser(); p.add_argument('username'); p.add_argument('password'); p.add_argument('--credits',type=int,default=50); a=p.parse_args()
    if not a.username or not a.password or a.credits<0: raise SystemExit('Datos inválidos')
    url=os.environ['SUPABASE_URL'].rstrip('/'); key=os.environ['SUPABASE_SERVICE_ROLE_KEY']
    r=requests.post(url+'/rest/v1/accounts',headers={'apikey':key,'Authorization':'Bearer '+key,'Content-Type':'application/json','Prefer':'return=representation'},json={'username':a.username,'password_hash':hash_password(a.password),'credits_remaining':a.credits},timeout=20)
    r.raise_for_status(); print('Cuenta creada:', a.username, 'créditos:', a.credits)
if __name__=='__main__': main()

