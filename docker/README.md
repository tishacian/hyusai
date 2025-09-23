# Docker

The files here are responsible for creating a docker image and deploying it on our servers (using kubernetes) or locally (using docker).

## Build and run OmniRAG monolith (old version)

For any local building / deployment, you need to [**install docker**](https://www.docker.com/products/docker-desktop/) on your machine, and launch it.

1. Build the image using `docker build . <your-image-tag>`
    - If you expect to run the image on a OVH instance, specify the destination platform using `--platform linux/amd64` (defaults to your machine)
    - If you expect to run the image on CPU, specify the destination type of device using `--build-arg DEVICE=cpu` (defaults to `gpu`)
2. Optional - Store your image in DockerHub:
    - Tag the image you just built using `docker tag <your-image-tag> <your-repo>:latest`
    - Push your image on your DockerHub repo using `docker push <your-repo>:latest`
3. Optional - Download your image on DockerHub using `docker pull <your-repo>:latest`
4. Configure your `.env` file. You can take `docker/example.env` as an example (default configuration).
4. Run your image using `docker run -p 8509:8509 --env-file <path-to-your-env-file> <your-image-tag>`
    - If you run the image on GPU, add `--gpus all` before your image tag.
    - If you want to mount a volume to share data (like VDBs) with your container, add `-v <data-folder-path> <destination-folder-path>` before you image tag.<br/>For example, if I want to provide my vector store folder located at `~/home/dev/vector_store/`, I will add `-v ~/home/dev/vector_store/ /app/vector_store/`

## Build and run Papai-LLM locally

0. Make your docker daemon is up.
1. Configure your nexus secrets in :
    - `docker/secrets/nexus_password.txt`
    - `docker/secrets/nexus_username.txt`
2. Tune your environment configurations if needed using the example .env files in the `test_env_files` folder.
3. Start all the required services using the `docker-composer.yml` file :
    - `docker compose up --build` (you might need to `export DOCKER_BUILDKIT=1` to enable secrets usage)
4. To stop the services, you can run:
    - `docker compose down` for simple stop
    - `docker compose down -v` for stop with data volumes removal
