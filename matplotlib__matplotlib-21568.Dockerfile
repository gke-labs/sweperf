FROM swebench/sweb.eval.x86_64.matplotlib_1776_matplotlib-21568:latest
# Ensure python3 and pexpect are installed (sometimes SWE-bench images have python but no pexpect)
RUN if command -v pip &> /dev/null; then pip install pexpect; else apt-get update && apt-get install -y python3-pexpect; fi
COPY replay.py /replay.py
COPY matplotlib__matplotlib-21568_trace.json /trace.json
ENTRYPOINT ["python3", "/replay.py", "/trace.json"]
