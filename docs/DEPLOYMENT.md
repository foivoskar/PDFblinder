# Deployment for untrusted submissions

The worker process is a fault/limit boundary, not a complete security boundary.
Local runs inherit the user's filesystem and network rights. Do not expose the
CLI directly as a publicly accessible service. A journal must validate its
actual isolation, patching, queue, access control and retention arrangement.

## Example Linux container deployment

The Dockerfile is a starting point, not a managed service. Local Docker testing
requires a running Docker daemon. CI builds it and smoke-tests a synthetic PDF.
Do not treat a successful build as security certification. Before production,
pin the base image by reviewed digest and maintain a patched/revalidated image.
Review the licensing obligations of distributing this Ghostscript-containing image.

Build in the project checkout:

```sh
docker build --build-arg SOURCE_REVISION="$(git rev-parse HEAD)" -t pdfblinder:review .
```

On a Linux host, create a dedicated private output directory and run one job:

```sh
mkdir -m 700 /absolute/private-job-output

docker run --rm \
  --network none \
  --read-only \
  --user "$(id -u):$(id -g)" \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  --memory 2g --memory-swap 2g --cpus 2 --pids-limit 64 \
  --tmpfs "/work:rw,noexec,nosuid,size=768m,mode=700,uid=$(id -u),gid=$(id -g)" \
  --mount type=bind,src=/absolute/input.pdf,dst=/input.pdf,readonly \
  --mount type=bind,src=/absolute/private-job-output,dst=/output \
  pdfblinder:review --timeout 120 /input.pdf /output/review.pdf
```

Use absolute paths appropriate to the host. Avoid root; allow access only to the
single input and this job's output directory. Do not mount home directories,
credentials, the Docker socket, other submissions or the editorial database.
Retain the host's default seccomp policy. Add site-specific AppArmor/SELinux
policy and filesystem quotas as appropriate. Keep the runtime network disabled.
The image is not needed for a trusted operator's ordinary desktop workflow.

This example gives the job write access to its output bind mount. Supervision
samples staging/disk sizes, but hard host quotas are still needed to limit output
and protect shared storage against a compromised parser. Memory and process limits
must be enforced by the host too; sampling alone is not a strict peak limit.
Run one submission per isolated job, with concurrency controlled by the service.

## Operational requirements

- Use encrypted, restricted local storage and private temporary directories.
- Avoid Dropbox/cloud synchronization for confidential originals, working data
  and audit reports unless the journal has explicitly approved that storage.
- Disable core dumps; control swap, host diagnostics and crash-report collection.
- The audit contains source-linking hashes. Keep it separate from reviewer files.
- Renderer diagnostics are intentionally not printed. Do not enable verbose
  third-party logging in a shared/public service without a redaction policy.
- Cancel the whole job/process tree; test timeout, quota, OOM and crash behavior.
- Clean up abandoned private job/staging directories using the site's retention
  policy. Ordinary file deletion does not prove forensic erasure.
- Keep original documents and output hashes for only the approved retention period.
- Validate the exact Ghostscript, PDFium, qpdf/pikepdf and OS versions after updates.
- Review dependencies and OS packages for vulnerabilities. A passing test suite
  and dependency audit are neither a guarantee of safety nor journal acceptance.

Any cloud hosting, shared service, logging destination or deletion policy needs
its own journal approval; this project does not configure or authorize it.
