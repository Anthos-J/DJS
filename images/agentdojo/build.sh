#!/usr/bin/env bash
set -eu
export PATH="/c/Users/SEBIN/AppData/Local/Programs/DockerDesktop/resources/bin:$PATH"
cd "$(dirname "$0")"
id=$(docker image inspect mandate-spike-py312:wave2 --format "{{.Id}}")
[ "$id" = sha256:44bc7e002d45a6d70020932c82aad758b9c8edcf077ab29ce8f08a443f21d90a ] || { echo "base image ID mismatch: $id"; exit 1; }
docker build --progress=plain -t mandate-agentdojo:wave5 . > build.log 2>&1
docker run --rm mandate-agentdojo:wave5 sh -c "python -V; pip show agentdojo | head -3; grep -iE \"^(agentdojo|cedarpy|pydantic)==\" /pip_freeze_agentdojo.txt" > image_manifest.txt
docker image inspect mandate-agentdojo:wave5 --format "image_id={{.Id}}" >> image_manifest.txt
cat image_manifest.txt
