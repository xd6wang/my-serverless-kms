FROM public.ecr.aws/lambda/python:3.9

# Install the function's dependencies using file requirements.txt
# from your project folder.

COPY requirements.txt  .
RUN yum -y install gcc wget && pip3 install -r requirements.txt --target "${LAMBDA_TASK_ROOT}" && \
    wget https://s3.amazonaws.com/cloudhsmv2-software/CloudHsmClient/EL7/cloudhsm-pkcs11-latest.el7.x86_64.rpm && \
    yum -y install ./cloudhsm-pkcs11-latest.el7.x86_64.rpm && \
    rm -rf ./cloudhsm-pkcs11-latest.el7.x86_64.rpm && \
    yum clean all && \
    rm -rf /var/cache/yum


COPY pkcs11/* /opt/cloudhsm/etc/

# Copy function code
COPY *.py ${LAMBDA_TASK_ROOT}/

# Set the CMD to your handler (could also be done as a parameter override outside of the Dockerfile)
# CMD [ "app.handler" ]
ENTRYPOINT []

CMD ["python3", "-m", "uvicorn", "main:app", "--proxy-headers", "--host", "0.0.0.0", "--port", "8080"]
