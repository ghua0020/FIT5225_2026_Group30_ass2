FROM public.ecr.aws/lambda/python:3.12

COPY backend/processing_pipeline/requirements.txt ${LAMBDA_TASK_ROOT}/requirements.txt
RUN python -m pip install --no-cache-dir \
        -r ${LAMBDA_TASK_ROOT}/requirements.txt && \
    python -m pip install --no-cache-dir --no-deps \
        protobuf==7.36.0 \
        onnx==1.16.1 \
        onnx2torch==1.5.15 && \
    python -m pip uninstall --yes opencv-python && \
    python -m pip install --no-cache-dir --no-deps --force-reinstall \
        opencv-python-headless==5.0.0.93

COPY backend/__init__.py ${LAMBDA_TASK_ROOT}/backend/__init__.py
COPY backend/processing_pipeline ${LAMBDA_TASK_ROOT}/backend/processing_pipeline

CMD ["backend.processing_pipeline.lambda_function.lambda_handler"]
