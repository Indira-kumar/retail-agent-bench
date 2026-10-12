#!/usr/bin/env sh

export EVAL_DATABASE_URL="${EVAL_DATABASE_URL:-postgresql://retail_eval:retail_eval_local@127.0.0.1:54329/retail_eval}"
export EVAL_AUDIO_S3_BUCKET="${EVAL_AUDIO_S3_BUCKET:-retail-eval-audio}"
export EVAL_AUDIO_S3_ENDPOINT_URL="${EVAL_AUDIO_S3_ENDPOINT_URL:-http://127.0.0.1:19000}"
export AWS_ACCESS_KEY_ID="${AWS_ACCESS_KEY_ID:-test}"
export AWS_SECRET_ACCESS_KEY="${AWS_SECRET_ACCESS_KEY:-test}"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"
