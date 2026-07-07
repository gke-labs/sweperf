FROM swebench/sweb.eval.x86_64.sphinx-doc_1776_sphinx-9602:latest
# Ensure python3 and pexpect are installed (sometimes SWE-bench images have python but no pexpect)
RUN if command -v pip &> /dev/null; then pip install pexpect; else apt-get update && apt-get install -y python3-pexpect; fi
COPY replay.py /replay.py
COPY sphinx-doc__sphinx-9602_trace.json /trace.json
ENTRYPOINT ["python3", "/replay.py", "/trace.json"]
