# Audit and deletion

## Find a run and check its storage

1. Open **Runs** to see the submitting user, catalogue name, and retained storage for each run.
2. Enter a user name, email address, catalogue title or slug, or part of a run identifier and click **Search**.
3. Select a status to combine it with the search. Click **Clear filters** to restore the full list.
4. Use **Older** and **Newer** to browse matching runs. Researchers see only their own runs.
5. Open a run for the same attribution and storage information alongside its tasks and results.

The catalogue name is the publication title recorded at submission. A run submitted directly by an administrator shows **Direct run**.

Retained storage is the sum of current file lengths in the run's workspace, stored outputs and logs, uploaded input sources, result ZIP files, and confirmed shared-storage deliveries. Files linked to several locations count once within the run. Original shared-storage inputs are excluded. An empty run shows **0 B**. A permission error produces an explicitly incomplete measurement. The value is a live snapshot; filesystem allocation, database storage, backups, and unrelated user uploads are excluded. An uploaded source reused by multiple runs counts towards each run, so adding the rows does not give the deployment's total storage usage.

## Review run history

1. Sign in as an administrator and open **Audit**.
2. Select **Runs** to see submissions and status changes. Scheduled runs are included.
3. Select an event type, or enter the complete run identifier, and click **Search audit**.
4. Expand **View details** for the recorded status, origin, and pipeline and publication identifiers.
5. Use **Older** and **Newer** to browse history.

Runs that predate this feature receive one explicitly labelled imported-history record. Earlier transitions cannot be reconstructed from the current run row.

## Delete a run and its files

1. Cancel an active run and wait until every task has stopped.
2. Open the run, click **Delete**, review the affected files, and confirm deletion.
3. Open **Audit → Deletion and file cleanup** and wait for **complete**.
4. If cleanup is **failed**, correct the reported storage problem and click **Retry cleanup**.

Deletion removes the run from normal views immediately. The reaper then removes its workspace, stored outputs, logs, manifests, result ZIP files, delivered copies, and uploaded inputs that no other live run or active or paused schedule uses. Original shared-storage input data is preserved. The cleanup request survives service restarts; it is complete only after the recorded file locations have been processed successfully. The reaper service must be running.

Cleanup is confined to configured storage roots. Missing shared mounts, changed mounts, symbolic links, and permission errors prevent a successful cleanup result. An existing destination that the delivery never confirmed also blocks deletion; retry that delivery or review the file's ownership first. Ensure the reaper service can write any configured shared output roots, including its systemd `ReadWritePaths` configuration. Correct these problems before retrying. Deployment backups and copies created outside the platform are governed by their own retention policies.

The run's database identity and audit records remain for historical provenance. They do not retain output-file contents.

## Delete withdrawn publications and pipeline versions

1. Withdraw a published entry before attempting to delete it.
2. On **Publications**, click **Delete** beside the withdrawn entry and confirm.
3. To delete a pipeline version, open its pipeline and click **Delete** beside the version.
4. Withdraw any live publication using that version if deletion is refused.
5. Check **Audit** for the deletion record.

Deleted versions cannot be selected for new runs or publications. Immutable historical definitions remain in the database so existing runs retain their provenance. Creating the same pipeline source again produces a new version rather than reusing a deleted version identifier.

## Remove a component

1. Open **Pipelines → Components**.
2. Use **View/Edit** to inspect a component, or **Remove** to request its removal.
3. Confirm removal and check the cleanup result on **Audit**.

Removal checks the selected source digest to prevent deleting another administrator's newer edit. Retained component snapshots support historical pipeline recompilation; the editable component file is removed. These controls and their backend endpoints are restricted to administrators.
