#!/bin/bash

DIR="$( cd "$(dirname "$0")" >/dev/null 2>&1 ; pwd -P )"
source $DIR/common.sh

exit_program()
{
  >&2 echo "$1 [-w workdir] [-f force_command] [-j threads]"
  >&2 echo ""
  >&2 echo "Runs several tests to check Bitextor is working"
  >&2 echo ""
  >&2 echo "OPTIONS:"
  >&2 echo "  -w <workdir>            Working directory. By default: \$HOME"
  >&2 echo "  -f <force_command>      Options which will be provided to snakemake"
  >&2 echo "  -j <threads>            Threads to use when running the tests"
  exit 1
}

WORK="${HOME}"
WORK="${WORK/#\~/$HOME}" # Expand ~ to $HOME
FORCE=""
THREADS=1

while getopts "hf:w:j:" i; do
    case "$i" in
        h) exit_program "$(basename "$0")" ; break ;;
        w) WORK=${OPTARG};;
        f) FORCE="--${OPTARG}";;
        j) THREADS="${OPTARG}";;
        *) exit_program "$(basename "$0")" ; break ;;
    esac
done
shift $((OPTIND-1))

BITEXTOR="bitextor-full ${FORCE} --notemp -j ${THREADS} -c ${THREADS} --reason"
BITEXTOR_EXTRA_ARGS=""
BICLEANER="${WORK}/bicleaner-model"
BICLEANER_AI="${WORK}/bicleaner-ai-model"
FAILS="${WORK}/data/fails.log"
mkdir -p "${WORK}"
mkdir -p "${WORK}/reports"
mkdir -p "${BICLEANER}"
mkdir -p "${BICLEANER_AI}"
mkdir -p "${WORK}/data/warc"
mkdir -p "${WORK}/data/parallel-corpus"
mkdir -p "${WORK}/data/prevertical"
rm -f "$FAILS"
touch "$FAILS"

# Download necessary files
# WARCs
download_warc "${WORK}/data/warc/greenpeace.warc.gz" https://github.com/bitextor/bitextor-data/releases/download/bitextor-warc-v1.1/greenpeace.canada-small.warc.gz &
# Bicleaner models
download_bicleaner_model "en-fr" "${BICLEANER}" &
download_bicleaner_ai_model "en-fr" "${BICLEANER_AI}" lite &
# Dictionaries
download_dictionary "en-fr" "${WORK}/permanent" &

wait

# MT (id >= 10)
(
    TRANSIENT_DIR="${WORK}/transient-mt-en-fr"

    mkdir -p "${TRANSIENT_DIR}" && \
    pushd "${TRANSIENT_DIR}" > /dev/null && \
    ${BITEXTOR} \
        --config profiling=True permanentDir="${WORK}/permanent/bitextor-mt-output-en-fr" \
            dataDir="${WORK}/data/data-mt-en-fr" transientDir="${TRANSIENT_DIR}" \
            warcs="['${WORK}/data/warc/greenpeace.warc.gz']" preprocessor="warc2text" shards=1 batches=512 lang1=en lang2=fr \
            documentAligner="externalMT" alignerCmd="bash ${DIR}/../bitextor/example/dummy-translate.sh" \
            sentenceAligner="bleualign" bicleaner=True bicleanerModel="${BICLEANER}/en-fr/en-fr.yaml" \
            bicleanerFlavour="classic" deferred=True tmx=True ${BITEXTOR_EXTRA_ARGS} \
        &> "${WORK}/reports/10-mt-en-fr.report" && \
    popd > /dev/null

    annotate_and_echo_info 10 "$?" "$(get_nolines ${WORK}/permanent/bitextor-mt-output-en-fr/en-fr.sent.gz)"
) &
(
    TRANSIENT_DIR="${WORK}/transient-mt-en-fr-p2t"

    if [[ ! -f "${WORK}/data/prevertical/greenpeace.en.prevertical.gz" ]] || \
       [[ ! -f "${WORK}/data/prevertical/greenpeace.fr.prevertical.gz" ]]; then
        mkdir -p "${WORK}/data/tmp-w2t"

        warc2text -o "${WORK}/data/tmp-w2t" -s -f "text,url" "${WORK}/data/warc/greenpeace.warc.gz" && \
        (
            python3 ${DIR}/utils/text2prevertical.py --text-files "${WORK}/data/tmp-w2t/en/text.gz" \
                --url-files "${WORK}/data/tmp-w2t/en/url.gz" --document-langs English --seed 1 \
            | pigz -c > "${WORK}/data/prevertical/greenpeace.en.prevertical.gz"
            python3 ${DIR}/utils/text2prevertical.py --text-files "${WORK}/data/tmp-w2t/fr/text.gz" \
                --url-files "${WORK}/data/tmp-w2t/fr/url.gz" --document-langs French --seed 2 \
            | pigz -c > "${WORK}/data/prevertical/greenpeace.fr.prevertical.gz" \
        )

        rm -rf "${WORK}/data/tmp-w2t"
    fi

    mkdir -p "${TRANSIENT_DIR}" && \
    pushd "${TRANSIENT_DIR}" > /dev/null && \
    ${BITEXTOR} \
        --config profiling=True permanentDir="${WORK}/permanent/bitextor-mt-output-en-fr-p2t" \
            dataDir="${WORK}/data/data-mt-en-fr-p2t" transientDir="${TRANSIENT_DIR}" \
            preverticals="['${WORK}/data/prevertical/greenpeace.en.prevertical.gz', '${WORK}/data/prevertical/greenpeace.fr.prevertical.gz']" \
            shards=1 batches=512 lang1=en lang2=fr documentAligner="externalMT" alignerCmd="bash ${DIR}/../bitextor/example/dummy-translate.sh" \
            sentenceAligner="bleualign" bicleaner=True bicleanerModel="${BICLEANER}/en-fr/en-fr.yaml" bicleanerFlavour="classic" \
            deferred=True tmx=True paragraphIdentification=True ${BITEXTOR_EXTRA_ARGS} \
        &> "${WORK}/reports/11-mt-en-fr-p2t.report" && \
    popd > /dev/null

    annotate_and_echo_info 11 "$?" "$(get_nolines ${WORK}/permanent/bitextor-mt-output-en-fr-p2t/en-fr.sent.gz)"
) &

# Dictionary-based (id >= 20)
(
    TRANSIENT_DIR="${WORK}/transient-en-fr"

    mkdir -p "${TRANSIENT_DIR}" && \
    pushd "${TRANSIENT_DIR}" > /dev/null && \
    ${BITEXTOR} \
        --config profiling=True permanentDir="${WORK}/permanent/bitextor-output-en-fr" \
            dataDir="${WORK}/data/data-en-fr" transientDir="${TRANSIENT_DIR}" \
            warcs="['${WORK}/data/warc/greenpeace.warc.gz']" preprocessor="warc2text" shards=1 batches=512 lang1=en lang2=fr \
            documentAligner="DIC" dic="${WORK}/permanent/en-fr.dic" sentenceAligner="hunalign" bicleaner=True bicleanerFlavour="classic" \
            bicleanerModel="${BICLEANER}/en-fr/en-fr.yaml" bicleanerThreshold=0.1 deferred=False tmx=True ${BITEXTOR_EXTRA_ARGS} \
        &> "${WORK}/reports/20-en-fr.report" && \
    popd > /dev/null

    annotate_and_echo_info 20 "$?" "$(get_nolines ${WORK}/permanent/bitextor-output-en-fr/en-fr.sent.gz)"
) &

wait

# MT and dictionary-based (id >= 60)
(
    TRANSIENT_DIR="${WORK}/transient-mtdb-en-fr"
    mkdir -p "${TRANSIENT_DIR}" && \
    pushd "${TRANSIENT_DIR}" > /dev/null && \
    ${BITEXTOR} \
        --config profiling=True permanentDir="${WORK}/permanent/bitextor-mtdb-output-en-fr" \
            dataDir="${WORK}/data/data-mtdb-en-fr" transientDir="${TRANSIENT_DIR}" \
            warcs="['${WORK}/data/warc/greenpeace.warc.gz']" preprocessor="warc2text" shards=1 batches=512 lang1=en lang2=fr \
            documentAligner="externalMT" alignerCmd="bash ${DIR}/../bitextor/example/dummy-translate.sh" \
            dic="${WORK}/permanent/en-fr.dic" sentenceAligner="hunalign" bicleaner=True bicleanerFlavour="classic" \
            bicleanerModel="${BICLEANER}/en-fr/en-fr.yaml" bicleanerThreshold=0.1 deferred=False tmx=True ${BITEXTOR_EXTRA_ARGS} \
        &> "${WORK}/reports/60-mtdb-en-fr.report" && \
    popd > /dev/null

    annotate_and_echo_info 60 "$?" "$(get_nolines ${WORK}/permanent/bitextor-mtdb-output-en-fr/en-fr.sent.gz)"
) &

# Other options (id >= 100)
(
    TRANSIENT_DIR="${WORK}/transient-mto1-en-fr"

    mkdir -p "${TRANSIENT_DIR}" && \
    pushd "${TRANSIENT_DIR}" > /dev/null && \
    ${BITEXTOR} \
        --config profiling=True permanentDir="${WORK}/permanent/bitextor-mto1-output-en-fr" \
            dataDir="${WORK}/data/data-mto1-en-fr" transientDir="${TRANSIENT_DIR}" \
            warcs="['${WORK}/data/warc/greenpeace.warc.gz']" preprocessor="warc2text" shards=1 batches=512 lang1=en lang2=fr \
            documentAligner="externalMT" alignerCmd="bash ${DIR}/../bitextor/example/dummy-translate.sh" sentenceAligner="bleualign" \
            deferred=False tmx=True deduped=True biroamer=True ${BITEXTOR_EXTRA_ARGS} \
        &> "${WORK}/reports/100-mto1-en-fr.report" && \
    popd > /dev/null

    annotate_and_echo_info 100 "$?" "$(get_nolines ${WORK}/permanent/bitextor-mto1-output-en-fr/en-fr.sent.gz)"
) &

(
    TRANSIENT_DIR="${WORK}/transient-mto2-en-fr"

    mkdir -p "${TRANSIENT_DIR}" && \
    pushd "${TRANSIENT_DIR}" > /dev/null && \
    ${BITEXTOR} \
        --config profiling=True permanentDir="${WORK}/permanent/bitextor-mto2-output-en-fr" \
            dataDir="${WORK}/data/data-mto2-en-fr" transientDir="${TRANSIENT_DIR}" \
            warcs="['${WORK}/data/warc/greenpeace.warc.gz']" preprocessor="warc2text" shards=1 batches=512 lang1=en lang2=fr \
            documentAligner="externalMT" documentAlignerThreshold=0.1 alignerCmd="bash ${DIR}/../bitextor/example/dummy-translate.sh" \
            sentenceAligner="bleualign" sentenceAlignerThreshold=0.1 \
            bicleaner=True bicleanerModel="${BICLEANER}/en-fr/en-fr.yaml" bicleanerFlavour="classic" bicleanerThreshold=0.0 \
            deferred=False bifixer=True tmx=True deduped=True biroamer=False ${BITEXTOR_EXTRA_ARGS} \
        &> "${WORK}/reports/101-mto2-en-fr.report" && \
    popd > /dev/null

    annotate_and_echo_info 101 "$?" "$(get_nolines ${WORK}/permanent/bitextor-mto2-output-en-fr/en-fr.sent.gz)"

    # Remove parallelism because NLTK model installation can't run in parallel (bifixer=True)

    TRANSIENT_DIR="${WORK}/transient-mto3-en-fr"

    mkdir -p "${TRANSIENT_DIR}" && \
    pushd "${TRANSIENT_DIR}" > /dev/null && \
    ${BITEXTOR} ${FORCE} --notemp -j ${THREADS} \
        --config profiling=True permanentDir="${WORK}/permanent/bitextor-mto3-output-en-fr" \
            dataDir="${WORK}/data/data-mto3-en-fr" transientDir="${WORK}/transient-mto3-en-fr" \
            warcs="['${WORK}/data/warc/greenpeace.warc.gz']" preprocessor="warc2text" shards=1 batches=512 lang1=en lang2=fr \
            documentAligner="externalMT" documentAlignerThreshold=0.1 alignerCmd="bash ${DIR}/../bitextor/example/dummy-translate.sh" \
            sentenceAligner="bleualign" sentenceAlignerThreshold=0.1 \
            bicleaner=True bicleanerModel="${BICLEANER_AI}/en-fr/metadata.yaml" bicleanerThreshold=0.0 \
            deferred=False bifixer=True tmx=True deduped=True biroamer=False ${BITEXTOR_EXTRA_ARGS} \
        &> "${WORK}/reports/102-mto3-en-fr.report" && \
    popd > /dev/null

    annotate_and_echo_info 102 "$?" "$(get_nolines ${WORK}/permanent/bitextor-mto3-output-en-fr/en-fr.sent.gz)"
) &

wait

# Results
failed=$(cat "$FAILS" | wc -l)

echo "------------------------------------"
echo "           Fails Summary            "
echo "------------------------------------"
echo "status | test-id | exit code / desc."
cat "$FAILS"

exit "$failed"
