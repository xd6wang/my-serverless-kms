from fastapi import FastAPI, status, HTTPException
import crypto
import base64
from typing import Optional
from pydantic import BaseModel
from anyio.lowlevel import RunVar
from anyio import CapacityLimiter


class Body(BaseModel):
    data: str
    key_label: Optional[str] = None
    key_type: Optional[str] = None


app = FastAPI()


repeater = None

@app.on_event("startup")
async def startup():
    global repeater
    # print("start")
    RunVar("_default_thread_limiter").set(CapacityLimiter(100))
    repeater = crypto.start_repeater()


@app.on_event("shutdown")
def shutdown_event():
    repeater.stop()


@app.get("/")
async def root():
    return "OK"


@app.post("/sign")
def sign(body: Body):
    try:
        print("MYDEBUG Body: " + str(body))
        data = base64.b64decode(body.data)

        signature = crypto.sign(data)
        retcontent = base64.b64encode(signature).decode("ascii")
        # print("Body:" + retcontent)
        return retcontent
    except Exception as e:
        print(f"Exception: {e.__class__.__name__}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail="Sign FAILED...")


@app.post("/encrypt")
def encrypt(body: Body):
    try:
        # print("Body: " + str(body))
        data = base64.b64decode(body.data)
        # print("data: " + data)
        ciphertext = crypto.encrypt(data)
        retcontent = base64.b64encode(ciphertext).decode("ascii")
        # print("Body:" + retcontent)
        return retcontent
    except Exception as e:
        print(f"Exception: {e.__class__.__name__}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail="Encryption FAILED...")


@app.post("/decrypt")
def decrypt(body: Body):
    try:
        # print("Body: " + str(body))
        data = base64.b64decode(body.data)
        # print("data: " + data)
        cleartext = crypto.decrypt(data)
        retcontent = base64.b64encode(cleartext).decode("ascii")
        # print("Body:" + retcontent)
        return retcontent
    except Exception as e:
        print(f"Exception: {e.__class__.__name__}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail="Decryption FAILED...")


@app.post("/test")
def test(body: Body):
    try:
        test_body = Body(data=encrypt(body))
        cleartext = decrypt(test_body)
        if cleartext == body.data:
            test_body.data = "PASS"
            return sign(test_body)
    except Exception as e:
        print(f"Exception: {e.__class__.__name__}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail="TEST FAILED...")
    
@app.get("/health")
def health_check():
    try:
        print("MYDEBUG: healthcheck")
        test(Body(data="aGVsbG8="))
    except Exception as e:
        print(f"Exception: {e.__class__.__name__}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail="HealthCheck FAILED...")