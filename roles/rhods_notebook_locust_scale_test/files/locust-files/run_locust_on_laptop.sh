#! /bin/bash

set -o errexit
set -o pipefail
set -o nounset
set -o errtrace
#set -x

THIS_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
BASE_DIR="$(realpath "$THIS_DIR")/../../../.."
source "$BASE_DIR/testing/ods/configure.sh"

LOCUST_COMMAND="rhods notebook_locust_scale_test"

_get_command_arg() {
    cd "$BASE_DIR"
    get_command_arg "$@"
}

export ODH_DASHBOARD_URL="https://$(oc get route -n redhat-ods-applications rhods-dashboard -ojsonpath={.spec.host})"
export TEST_USERS_USERNAME_PREFIX=$(_get_command_arg username_prefix $LOCUST_COMMAND)
export TEST_USERS_IDP_NAME=$(_get_command_arg idp_name $LOCUST_COMMAND)
export USER_INDEX_OFFSET=$(_get_command_arg user_index_offset $LOCUST_COMMAND)

export CREDS_FILE=$(_get_command_arg secret_properties_file $LOCUST_COMMAND)
export NOTEBOOK_IMAGE_NAME=$(_get_command_arg notebook_image_name $LOCUST_COMMAND)
export NOTEBOOK_SIZE_NAME=$(_get_command_arg notebook_size_name $LOCUST_COMMAND)


export LOCUST_USERS=$(_get_command_arg user_count $LOCUST_COMMAND)
export LOCUST_SPAWN_RATE=$(_get_command_arg spawn_rate $LOCUST_COMMAND)
export LOCUST_RUN_TIME=$(_get_command_arg run_time $LOCUST_COMMAND)
# or
#export LOCUST_ITERATIONS=1


export LOCUST_LOCUSTFILE=$THIS_DIR/locustfile.py

export REUSE_COOKIES=1

DEBUG_MODE=${DEBUG_MODE:-1}
export DEBUG_MODE

if [[ "$DEBUG_MODE" == 1 ]]; then
    echo "Debug!"
    exec python3 "$LOCUST_LOCUSTFILE"
fi

unset LOCUST_RUN_TIME
mkdir -p results
rm results/* -f
echo "Run!"


WORKER_COUNT=4
# distributed locust options
export LOCUST_EXPECT_WORKERS=${WORKER_COUNT}
export LOCUST_EXPECT_WORKERS_MAX_WAIT=$((3 + ${WORKER_COUNT} / 10))

export LOCUST_HEADLESS=1
export LOCUST_RESET_STATS=1
export LOCUST_CSV=results/api_scale_test
export LOCUST_HTML=$LOCUST_CSV.html
export LOCUST_ONLY_SUMMARY=1

unset process_ctrl__wait_list
declare -A process_ctrl__wait_list

locust --master &
MASTER_PID=$!

finish() {
    trap - INT
    echo "Killing the background processes still running ..."
    for pid in ${!process_ctrl__wait_list[@]}; do
        echo "- ${process_ctrl__wait_list[$pid]} (pid=$pid)"
        kill -KILL $pid 2>/dev/null || true
        unset process_ctrl__wait_list[$pid]
    done
    echo "All the processes have been terminated."

    kill -KILL $MASTER_PID
    echo "Waiting ..."
    wait $MASTER_PID

    locust-reporter \
        -prefix results/api_scale_test \
        -failures=true \
        -outfile results/locust_reporter.html
}

trap finish INT

# locust clients don't like that to be set
unset LOCUST_RUN_TIME

sleep 1 # give 1s for the locust coordinator to be ready
for worker in $(seq 1 ${CPU_COUNT})
do
    sleep 0.1
    locust --worker &
    pid=$!
    process_ctrl__wait_list[$pid]="locust --worker"
done

wait $MASTER_PID
