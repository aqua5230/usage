FROM gcr.io/oss-fuzz-base/base-builder-python@sha256:13e428067eac23eafc5ccf570ff2fb19beab981036b00b5d90902c20da1cc236

WORKDIR $SRC/usage

COPY . $SRC/usage
COPY fuzz/ $SRC/fuzz/
COPY .clusterfuzzlite/project.yaml $SRC/project.yaml
COPY .clusterfuzzlite/build.sh $SRC/build.sh
