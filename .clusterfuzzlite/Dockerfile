FROM gcr.io/oss-fuzz-base/base-builder-python

WORKDIR $SRC/usage

COPY . $SRC/usage
COPY fuzz/ $SRC/fuzz/
COPY .clusterfuzzlite/project.yaml $SRC/project.yaml
COPY .clusterfuzzlite/build.sh $SRC/build.sh
