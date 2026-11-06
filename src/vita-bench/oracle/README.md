# Oracle trajectories

One validated conversation per task, `<task_set>/<source_task_id>.json`, in the
exact format written by the `vita-runtime` sidecar. Populated by
`scripts/build_oracle.py` from Harbor job outputs; the adapter copies each file to
`solution/oracle_trajectory.json` of the matching task.
