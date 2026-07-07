FROM swebench/sweb.eval.x86_64.scikit-learn_1776_scikit-learn-26323:latest
# Ensure python3 and pexpect are installed (sometimes SWE-bench images have python but no pexpect)
RUN if command -v pip &> /dev/null; then pip install pexpect; else apt-get update && apt-get install -y python3-pexpect; fi
COPY replay.py /replay.py
COPY scikit-learn__scikit-learn-26323_trace.json /trace.json
ENTRYPOINT ["python3", "/replay.py", "/trace.json"]
