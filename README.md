# Serverless Infrastructure for Handling Zoom Meeting Recordings

## Set up environment for development
1. `cd serverless-zoom-recordings`
1. `PIPENV_VENV_IN_PROJECT=1 pipenv install --dev`
1. `pipenv shell` 
1. `nodeenv -p` # Installs Node environment inside Python environment
1. `npm install --include=dev` # Installs Node packages inside combined Python/Node environment
1. `exit` # For serverless to install correctly in the environment...
1. `pipenv shell` # ...we need to exit out and re-enter the environment
1. `npm install -g serverless` # Although the '-g' global flag is being used, Serverless install is in the Python/Node environment

## Before deploying the production stack
1. `serverless create_domain --aws-profile olf`

## Steps

### [Zoom Webhook](serverless_zoom_recordings/zoom_webhook.py)
1. Accept the webhook message from Zoom, test for validity
1. Invoke the Step Function

### [Recording Intake](serverless_zoom_recordings/ingest_metadata.py)
1. Store recording details in S3 and database
1. Get past meeting metadata from Zoom, store in S3 folder
1. Get parent meeting metadata from Zoom, store in S3 folder
1. Prepare parallel recording retrieval

### [Retrieve Recording](serverless_zoom_recordings/retrieve_recording.py)
1. Range-based retrieval from Zoom and put to S3 as multi-part upload
1. Output file metadata in JSON

### Clean-up
1. Write recording document to S3 and database
1. Move Zoom recording to trash
1. Enqueue message to website builder

## Other tasks

### Retrieve missed meetings
1. Scan through OLF accounts looking for missed meetings

### Delete old recordings
1. Search for meetings with disposition entries

### Rebuild database
1. Scan S3 bucket to rebuild event database 

### Modify meeting recording document
1. Download the `meeting_recording.json` document and modify to taste
2. Invoke the *reindex_recording* endpoint: `sls invoke --stage prod --aws-profile olf --function reindex_recording --path ~/Downloads/recording_document.json`

### Manually ingest a recording from Zoom
1. Retrieve the JSON of the Zoom webhook. (For example, go into the StepFunction execution and pull the JSON from there, then edit to needs.)
1. Invoke the *invoke_stepfunction* endpoint: `sls invoke --aws-profile olf --stage prod --function invoke_stepfunction --path zoom_webhook.json`