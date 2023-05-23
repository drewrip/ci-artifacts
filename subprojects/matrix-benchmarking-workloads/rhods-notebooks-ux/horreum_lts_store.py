import types
import datetime
import json
from pathlib import PosixPath
from collections import defaultdict, OrderedDict
import logging

from .plotting import prom

import matrix_benchmarking.store as store
import matrix_benchmarking.store.simple as store_simple
import matrix_benchmarking.common as common
import matrix_benchmarking.cli_args as cli_args

lts_metrics = {
    'sutest': []
}

def register_lts_metric(cluster_role, metric):
    for (name, query) in metric.items():
        lts_metrics[cluster_role].append((name, query))


def _parse_lts_dir(add_to_matrix, dirname, import_settings):
    with open(dirname / "data.json") as f:
        data = json.load(f)

    add_to_matrix(_encode_json(data, dirname, data["settings"]))


def _parse_entry(val):
    type_skiplist = [PosixPath, types.FunctionType]

    val_type = type(val)

    if val_type is datetime.datetime:
        return datetime.datetime.timestamp(val)

    elif val_type in [dict, types.SimpleNamespace, common.MatrixEntry, defaultdict, list]:
        return _decode_ci_items(val)

    elif val_type not in type_skiplist:
        return val


def _decode_ci_items(src_obj):
    src_obj_type = type(src_obj)

    if src_obj_type == list:
        new_obj = [_parse_entry(val) for val in src_obj ]

    elif src_obj_type in [types.SimpleNamespace, common.MatrixEntry, dict, defaultdict]:
        _src_obj = vars(src_obj) \
            if src_obj_type in [types.SimpleNamespace, common.MatrixEntry] \
            else src_obj

        new_obj = {key: _parse_entry(val) for key, val in _src_obj.items()}

    else:
        new_obj = src_obj

    return new_obj


def _encode_entry(src_obj):
    src_obj_type = type(src_obj)

    if src_obj_type == list:
        return [_encode_entry(val) for val in src_obj]
    elif src_obj_type is not dict:
        return src_obj

    result = {}

    final_type = src_obj.get("$type", "dict")
    try: del src_obj['$type']
    except Exception: pass

    if final_type == "datetime":
        return datetime.datetime.fromtimestamp(src_obj.get('value'))

    for key, val in src_obj.items():
        result[key] = _encode_entry(val)

    if final_type == "defaultdict":
        return defaultdict(types.SimpleNamespace, result)

    elif final_type == "SimpleNamespace":
        return types.SimpleNamespace(**result)

    return result


def _encode_json(src_obj, name, settings):
    del src_obj['$schema']

    data = _encode_entry(src_obj)

    return common.MatrixEntry(import_key=name, processed_settings=settings, **data)


def build_lts_payloads() -> dict:
    for entry in common.Matrix.processed_map.values():
        results = entry.results

        start_time: datetime.datetime = results.start_time
        end_time: datetime.datetime = results.end_time

        output = {
            "$schema": "urn:rhods-matbench-upload:3.0.0",
            "data": {
                "users": _decode_users(results),
                'rhods_version': results.rhods_info.version,
                'ocp_version': results.sutest_ocp_version,
                'metrics': _gather_prom_metrics(entry),
                'thresholds': results.thresholds,
                'config': results.test_config.yaml_file
            },
            "metadata": {
                "test": "rhods-notebooks-ux",
                "start": start_time.isoformat(),
                "end": end_time.isoformat(),
                "settings": _parse_entry(entry.settings)
            }
        }

        yield output, start_time, end_time


def _decode_users(results):
    output = []
    for user_idx, ods_ci in getattr(results, "ods_ci", {}).items():
        if not hasattr(ods_ci, "output"): continue

        output.append({
            'hostname': results.testpod_hostnames.get(user_idx, None),
            'steps': _decode_steps(ods_ci.output, results.notebook_pod_times.get(user_idx)),
            'succeeded': ods_ci.exit_code == 0
        })

    return output


def _decode_steps(steps, pod_times):
    out_steps = []
    for step_name, step_data in steps.items():
        out_step = {
            'name': step_name,
            'duration': (step_data.finish - step_data.start).total_seconds(),
            'status': step_data.status
        }
        if step_name in ("Wait for the Notebook Spawn", "Create and Start the Workbench"):
            out_step['substeps'] = _generate_pod_timings(pod_times, step_data.start, step_data.finish)

        out_steps.append(out_step)

    return out_steps


def _generate_pod_timings(pod_times, start, end):
    output = {}

    if hasattr(pod_times, "pod_scheduled"):
        output['resource_init_time'] = (pod_times.pod_scheduled - start).total_seconds()
    if hasattr(pod_times, "containers_ready"):
        output['container_ready_time'] = (pod_times.containers_ready - pod_times.pod_initialized).total_seconds()
    if hasattr(pod_times, 'containers_ready'):
        output['user_notification'] = (end - pod_times.containers_ready).total_seconds()

    return output


def _gather_prom_metrics(entry) -> dict:
    output = {}

    for cluster_role, metric_names in lts_metrics.items():
        for metric_name in metric_names:
            logging.info(f"Gathering {metric_name[0]}")
            output[metric_name[0]] = {
                'data': prom.get_metrics('sutest')(entry, metric_name[0]),
                'query': metric_name[1]
            }

    return output