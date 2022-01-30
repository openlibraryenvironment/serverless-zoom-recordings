# Serverless Infrastructure for Handling Zoom Meeting Recordings

## Set up environment
1. `cd serverless-zoom-recordings`
1. `PIPENV_VENV_IN_PROJECT=1 pipenv install --dev`
1. `pipenv shell` 
1. `nodeenv -p` # Installs Node environment inside Python environment
1. `npm install -g serverless` # Although the '-g' global flag is being used, Serverless install is in the Python/Node environment
1. `rehash` # Pick up the serverless executable in the .venv/bin path
1. `npm install --include=dev` # Installs Node packages inside combined Python/Node environment

## Steps

### Zoom Webhook
1. Accept the webhook message from Zoom, test for validity
1. Invoke the Step Function

### Recording Intake
1. Store recording details in S3 and database
1. Get past meeting metadata from Zoom, store in S3 folder and database
1. Get parent meeting metadata from Zoom, store in S3 folder and database
1. Prepare parallel recording retrieval

