from fastapi import FastAPI , Request, Response
import datetime

def request_log(request : Request, response : Response ):
   time = datetime.now()
   content = time.isoformat() + "\n client" + request.client+host+"\n method" + request.method + "\n url path" + request.url.path + '\n response code' + Response.status_code 
   with open("request_logs.txt","a") as f:
        f.write(content)

#to do docker logging, volume

# full request and response logging 

#errors 

#registration/loging errors 