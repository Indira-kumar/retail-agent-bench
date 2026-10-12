#!/usr/bin/env sh
set -eu

awslocal s3api head-bucket --bucket retail-eval-audio >/dev/null 2>&1 || \
  awslocal s3api create-bucket --bucket retail-eval-audio
