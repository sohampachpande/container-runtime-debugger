# Debugging Workflow: Container OOM Kill

This workflow diagnoses a Dockerized application that stops responding while handling a memory-intensive request.

## Test setup

The demo container has a 64 MiB memory limit. Trigger the failure with:

~~~sh
curl 'http://localhost:8080/allocate?mb=1024'
~~~

An empty reply from the server means the service stopped while processing the request. It does not identify the cause.

## 1. Inspect application logs

~~~sh
docker logs container-runtime-debugger-demo-app-1
~~~

The demo logs allocation progress every 8 MiB. If logging stops during allocation, the process likely terminated before it could return a response.

## 2. Inspect the container exit state

~~~sh
docker inspect container-runtime-debugger-demo-app-1 \
  --format 'Running={{.State.Running}} OOMKilled={{.State.OOMKilled}} ExitCode={{.State.ExitCode}}'
~~~

Expected result after the test:

~~~text
Running=false OOMKilled=true ExitCode=137
~~~

OOMKilled=true attributes the termination to the Linux kernel's out-of-memory handling. Exit code 137 means the process received SIGKILL (128 + 9).

## 3. Confirm the configured limit

~~~sh
docker inspect container-runtime-debugger-demo-app-1 \
  --format 'Memory={{.HostConfig.Memory}}'
~~~

The expected result is Memory=67108864, which is 64 MiB. Together with the logs and exit state, this establishes the incident:

~~~text
Memory-intensive request
  → application logs stop during allocation
  → process exits with SIGKILL
  → Docker reports OOMKilled=true
  → configured cgroup memory limit was 64 MiB
~~~

## Useful live signals

~~~sh
# Observe current CPU and memory use while reproducing the issue.
docker stats container-runtime-debugger-demo-app-1

# Observe container lifecycle events.
docker events
~~~

## Future eBPF stage

An eBPF collector will observe the kernel OOM event directly, capture the PID and cgroup identity, associate it with the container, and export a metric. That will provide kernel-level attribution without waiting for the Docker exit-state inspection.
