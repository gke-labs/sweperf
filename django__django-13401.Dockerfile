FROM swebench/sweb.eval.x86_64.django_1776_django-13401:latest
# Ensure python3 and pexpect are installed (sometimes SWE-bench images have python but no pexpect)
RUN if command -v pip &> /dev/null; then pip install pexpect; else apt-get update && apt-get install -y python3-pexpect; fi
COPY replay.py /replay.py
COPY django__django-13401_trace.json /trace.json
ENTRYPOINT ["python3", "/replay.py", "/trace.json"]
