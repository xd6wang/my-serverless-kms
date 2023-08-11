import pkcs11
from pkcs11 import KeyType
import queue
from pkcs11.exceptions import (
    DeviceError,
    DeviceRemoved,
    OperationNotInitialized,
    FunctionFailed,
)
import boto3
import time
import logging
import sys
import backoff
from functools import wraps
from collections import defaultdict
from statistics import mean
import base64
from botocore.exceptions import ClientError
import json
from repeater import RepeatedTimer


# from functools import wraps, partial
# import asyncio


# def async_wrap(func):
#     @wraps(func)
#     async def run(*args, loop=None, executor=None, **kwargs):
#         if loop is None:
#             loop = asyncio.get_event_loop()
#         pfunc = partial(func, *args, **kwargs)
#         return await loop.run_in_executor(executor, pfunc)
#     return run


max_time = 10
lib = None
token = None
session = None
# queue_size = 50
put_metric_interval = 10
region_name = 'us-east-1'
secret_name = "prod/mykms/user"

# q_sign = queue.Queue(queue_size)
# q_encrypt = queue.Queue(queue_size)
q_metrics = queue.Queue()

private_key_class = None
secret_key_class = None
private_key_handle = None
secret_key_handle = None


logging.getLogger("backoff").addHandler(logging.StreamHandler(sys.stdout))


def get_secret():
    client = boto3.client('secretsmanager', region_name=region_name)

    try:
        get_secret_value_response = client.get_secret_value(
            SecretId=secret_name
        )
    except ClientError as e:
        if e.response['Error']['Code'] == 'DecryptionFailureException':
            # Secrets Manager can't decrypt the protected secret text using the provided KMS key.
            # Deal with the exception here, and/or rethrow at your discretion.
            raise e
        elif e.response['Error']['Code'] == 'InternalServiceErrorException':
            # An error occurred on the server side.
            # Deal with the exception here, and/or rethrow at your discretion.
            raise e
        elif e.response['Error']['Code'] == 'InvalidParameterException':
            # You provided an invalid value for a parameter.
            # Deal with the exception here, and/or rethrow at your discretion.
            raise e
        elif e.response['Error']['Code'] == 'InvalidRequestException':
            # You provided a parameter value that is not valid for the current state of the resource.
            # Deal with the exception here, and/or rethrow at your discretion.
            raise e
        elif e.response['Error']['Code'] == 'ResourceNotFoundException':
            # We can't find the resource that you asked for.
            # Deal with the exception here, and/or rethrow at your discretion.
            raise e
        else:
            raise e
    else:
        # Decrypts secret using the associated KMS key.
        # Depending on whether the secret is a string or binary, one of these fields will be populated.
        if 'SecretString' in get_secret_value_response:
            secret = get_secret_value_response['SecretString']
            return secret
        else:
            decoded_binary_secret = base64.b64decode(get_secret_value_response['SecretBinary'])
            return decoded_binary_secret


@backoff.on_exception(backoff.expo, (DeviceError, FunctionFailed), max_time=max_time)
def initialize():
    global lib, token
    lib = pkcs11.lib("/opt/cloudhsm/lib/libcloudhsm_pkcs11.so")
    token = lib.get_token()


# @backoff.on_exception(backoff.expo, (DeviceError, FunctionFailed), max_time=max_time)
# def reinitialize():
#     global lib, token
#     lib.reinitialize()
#     token = lib.get_token()

secret = json.loads(get_secret())

@backoff.on_exception(backoff.expo, (DeviceError, FunctionFailed, DeviceRemoved), max_time=max_time)
def get_session(auth=False):
    global token, session

    if auth:
        session = token.open(rw=True, user_pin=f'{secret["CU_Name"]}:{secret["Password"]}')
    else:
        session = token.open(rw=True)
    # print("sessionopened")
    return session


@backoff.on_exception(backoff.expo, (DeviceError, FunctionFailed, DeviceRemoved), max_time=max_time)
def get_key(session, key_type, label, object_class):
    return session.get_key(key_type=key_type, label=label, object_class=object_class)


def try_close_session(session):
    try:
        session.close()
    except:
        pass


def init_keys():
    session = get_session(True)
    global private_key_class
    global secret_key_class
    global private_key_handle
    global secret_key_handle
    private = get_key(session, KeyType.EC, label="1st-p256", object_class=3)
    private_key_class = type(private)
    private_key_handle = private._handle
    key = get_key(session, KeyType.AES, label="1st", object_class=4)
    secret_key_class = type(key)
    secret_key_handle = key._handle
    

print("Startinitialize")
initialize()
print("Doneinitialize")
init_keys()
print("Doneinitkeys")


def put_metric():
    metrics = defaultdict(list)
    metric_data = []
    queue_size = q_metrics.qsize()
    # print(f"metric queue size is: {queue_size}")
    for x in range(queue_size):
        time_eclapsed, operation = q_metrics.get()
        metrics[operation].append(time_eclapsed)
    for operation, responses in metrics.items():
        metric_data.append({
                "MetricName": "Duration",
                "Dimensions": [{"Name": "Operation", "Value": operation}],
                "Unit": "Seconds",
                "Value": mean(responses),
                "StorageResolution": 1,
            })
    if metric_data:
        # print("put_metric {} operation types".format(len(metric_data)))
        # print(metric_data)
        cloudwatch = boto3.client("cloudwatch", region_name=region_name)
        cloudwatch.put_metric_data(
            MetricData=metric_data,
            Namespace="Mykms",
        )
        # print("put_metric done")


def start_repeater():
    return RepeatedTimer(put_metric_interval, put_metric)


def timeit(func):
    @wraps(func)
    def wrap(*args, **kwargs):
        global q_metrics
        start = time.perf_counter()
        result = func(*args, **kwargs)
        end = time.perf_counter()
        time_eclapsed = end - start
        try:
            # put_metric(time_eclapsed, func.__name__)
            q_metrics.put((time_eclapsed, func.__name__))
        except Exception as e:
            print("timeit exception: " + e.__class__.__name__)
        return result

    return wrap


# def try_refresh_session(func):
#     def wrap(*args, **kwargs):
#         try:
#             print("normaltry")
#             return func(*args, **kwargs)
#         except (DeviceError, DeviceRemoved):
#             print("trygrefresh")
#             get_session()
#             print("donerefresh")
#             return func(*args, **kwargs)
#         except OperationNotInitialized:
#             print("closesession")
#             session.close()
#             print("getanewsession")
#             get_session()
#             print("doneanewsession")
#             return func(*args, **kwargs)
#     return wrap

# async def sign(data, key_label="1st-p256"):
#     # print("intosign")
#     session = token.open(rw=True)
#     private = await async_wrap(session.get_key)(key_type=KeyType.EC, label=key_label, object_class=3)
#     # Given a private key `private`
#     # print("beginsign")
#     signature = await async_wrap(private.sign)(data)
#     # print("endsign")
#     # print(data + ": " + str(signature))
#     await async_wrap(session.close)()
#     return signature

# @try_refresh_session
@timeit
def sign(data):
    print("MYDEBUG: get_session()")
    with get_session() as session:
        print(f"MYDEBUG: createprivatekeyobject, {session}, {private_key_handle}")
        private = private_key_class(session, private_key_handle)
        print("MYDEBUG: donecreateprivatekeyobject")
        print("MYDEBUG: startsign")
        signature = private.sign(data)
        print("MYDEBUG: endsign")
        return signature


# @try_refresh_session
@timeit
def encrypt(data):
    with get_session() as session:
        key = secret_key_class(session, secret_key_handle)
        # Get an initialisation vector
        iv = session.generate_random(128)  # AES blocks are fixed at 128 bits
        # Encrypt our data
        ciphertext = key.encrypt(data, mechanism_param=iv)
    
        return iv + ciphertext


# @try_refresh_session
@timeit
def decrypt(data):

    # Get an initialisation vector
    iv = data[:16]
    ciphertext = data[16:]
    with get_session() as session:
        key = secret_key_class(session, secret_key_handle)
        plaintext = key.decrypt(ciphertext, mechanism_param=iv)
    
        return plaintext


# async def main():
#     tasks=[]
#     for _ in range(1000):
#         tasks.append(sign("hello"))
#     await asyncio.gather(*tasks)


# asyncio.run(main())
