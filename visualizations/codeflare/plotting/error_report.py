import copy
import re
from collections import defaultdict
import os
import base64
import pathlib
import yaml

from dash import html
from dash import dcc

from matrix_benchmarking.common import Matrix
import matrix_benchmarking.plotting.table_stats as table_stats
import matrix_benchmarking.common as common

from . import report

def register():
    ErrorReport()


def _get_time_to_last_launch(entry):
    if not entry.results.resource_times:
        return 0, None

    target_kind = "Job" if entry.results.test_case_properties.job_mode else "AppWrapper"
    resource_time = sorted([resource_time for resource_time in entry.results.resource_times.values() if resource_time.kind == target_kind], key=lambda t: t.creation)[-1]

    start_time = entry.results.test_start_end_time.start

    last_launch = resource_time.creation
    return (last_launch - start_time).total_seconds() / 60, last_launch


def _get_time_to_last_schedule(entry):
    if not entry.results.pod_times:
        return 0, None

    pod_time = sorted(entry.results.pod_times, key=lambda t: t.pod_scheduled)[-1]

    start_time = entry.results.test_start_end_time.start

    last_schedule = pod_time.pod_scheduled
    return (last_schedule - start_time).total_seconds() / 60, last_schedule


def _get_test_setup(entry):
    if entry.is_lts:
        return []

    setup_info = []

    artifacts_basedir = entry.results.from_local_env.artifacts_basedir

    if artifacts_basedir:
        setup_info += [html.Li(html.A("Results artifacts", href=str(artifacts_basedir), target="_blank"))]

    else:
        setup_info += [html.Li(f"Results artifacts: NOT AVAILABLE ({entry.results.from_local_env.source_url})")]

    mcad_log_file = entry.results.from_local_env.artifacts_basedir / entry.results.file_locations.mcad_logs
    setup_info += [html.Li(html.A("MCAD logs", href=str(mcad_log_file), target="_blank"))]
    test_config_file = entry.results.from_local_env.artifacts_basedir / entry.results.file_locations.test_config_file
    setup_info += [html.Li(html.A("Test configuration", href=str(test_config_file), target="_blank"))]

    managed = list(entry.results.cluster_info.control_plane)[0].managed \
        if entry.results.cluster_info.control_plane else False

    sutest_ocp_version = entry.results.sutest_ocp_version


    setup_info += [html.Li(["Test running on ", "OpenShift Dedicated" if managed else "OCP", html.Code(f" v{sutest_ocp_version}")])]

    nodes_info = [
        html.Li([f"Total of {len(entry.results.cluster_info.node_count)} nodes in the cluster"]),
    ]

    for purpose in ["control_plane", "infra"]:
        nodes = entry.results.cluster_info.__dict__.get(purpose)

        purpose_str = f" {purpose} nodes"
        if purpose == "control_plane": purpose_str = f" nodes running OpenShift control plane"
        if purpose == "infra": purpose_str = " nodes, running the OpenShift and RHODS infrastructure Pods"

        if not nodes:
            node_count = 0
            node_type = "n/a"
        else:
            node_count = len(nodes)
            node_type = list(nodes)[0].instance_type

        nodes_info_li = [f"{node_count} ", html.Code(node_type), purpose_str]

        nodes_info += [html.Li(nodes_info_li)]

    setup_info += [html.Ul(nodes_info)]

    setup_info += [html.Li(["MCAD version: ", html.B(entry.results.mcad_version)])]

    test_duration = (entry.results.test_start_end_time.end - entry.results.test_start_end_time.start).total_seconds() / 60
    test_speed = entry.results.test_case_properties.total_pod_count / test_duration
    setup_info += [html.Li(["Test duration: ", html.Code(f"{test_duration:.1f} minutes")])]

    setup_info += [html.Ul(html.Li(["Launch speed of ", html.Code(f"{entry.results.test_case_properties.total_pod_count/entry.results.test_case_properties.launch_duration:.2f} Pod/minute")]))]
    setup_info += [html.Ul(html.Li(["Test speed of ", html.Code(f"{test_speed:.2f} Pod/minute")]))]

    time_to_last_schedule, last_schedule_time = _get_time_to_last_schedule(entry)
    time_to_last_launch, last_launch_time = _get_time_to_last_launch(entry)

    if last_schedule_time:
        setup_info += [html.Li(["Time to last Pod schedule: ", html.Code(f"{time_to_last_schedule:.1f} minutes")])]
        setup_info += [html.Ul(html.Li(["Test speed of ", html.Code(f"{time_to_last_schedule:.2f} Pod/minute")]))]
        setup_info += [html.Ul(html.Li(["Time between the last resource launch and its schedule: ", html.Code(f"{(last_schedule_time - last_launch_time).total_seconds()} seconds")]))]

    setup_info += [html.Li(["Test-case configuration: ", html.B(entry.settings.name), html.Code(yaml.dump(entry.results.test_case_config), style={"white-space": "pre-wrap"})])]
    return setup_info

class ErrorReport():
    def __init__(self):
        self.name = "report: Error report"
        self.id_name = self.name.lower().replace(" ", "_")
        self.no_graph = True
        self.is_report = True

        table_stats.TableStats._register_stat(self)

    def do_plot(self, *args):
        ordered_vars, settings, setting_lists, variables, cfg = args

        if common.Matrix.count_records(settings, setting_lists) != 1:
            return {}, "ERROR: only one experiment must be selected"

        for entry in common.Matrix.all_records(settings, setting_lists):
            pass

        header = []
        header += [html.P("This report shows the list of users who failed the test, with a link to their execution report and the last screenshot taken by the Robot.")]
        header += [html.H1("Error Report")]

        setup_info = _get_test_setup(entry)

        if entry.results.from_local_env.is_interactive:
            # running in interactive mode
            def artifacts_link(path):
                if path.suffix != ".png":
                    return f"file://{entry.results.from_local_env.artifacts_basedir / path}"
                try:
                    with open (entry.results.from_local_env.artifacts_basedir / path, "rb") as f:
                        encoded_image = base64.b64encode(f.read()).decode("ascii")
                        return f"data:image/png;base64,{encoded_image}"
                except FileNotFoundError:
                    return f"file://{entry.results.from_local_env.artifacts_basedir / path}#file_not_found"
        else:
            artifacts_link = lambda path: entry.results.from_local_env.artifacts_basedir / path


        header += [html.Ul(
            setup_info
        )]


        header += [html.H2("Pod Completion Progress")]

        header += report.Plot_and_Text(f"Pod Completion Progress", args)
        header += html.Br()
        header += html.Br()

        header += report.Plot_and_Text(f"Resource Mapping Timeline", args)

        return None, header
