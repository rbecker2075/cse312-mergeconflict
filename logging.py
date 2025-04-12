from fastapi import FastAPI , Request
import datetime


def request_log(request : Request):
   time = datetime.now()
   content = time.isoformat() + "\n" + request.client+host+"\n" + request.method + "\n" + request.url.path + '\n'
   with open("request_logs.txt","a") as f:
        f.write(content)

