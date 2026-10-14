from pathlib import Path
root=Path('/workspace/agentium')
work=Path('/workspace/dataops-image-qualification')
# CA is a public trust bundle, injected only while RUN executes; it is never a layer.
for name in ('backend','worker'):
    original=root/f'docker/Dockerfile.agentium-{name}'
    target=work/f'Dockerfile.{name}'
    content=original.read_text().replace('RUN ', 'RUN --mount=type=secret,id=proxy_ca,required=true export PIP_CERT=/run/secrets/proxy_ca REQUESTS_CA_BUNDLE=/run/secrets/proxy_ca SSL_CERT_FILE=/run/secrets/proxy_ca; ',)
    target.write_text(content)
    Path(str(target)+'.dockerignore').write_text(Path(str(original)+'.dockerignore').read_text())
    # This stage exists only in a separate verification Dockerfile. The measured
    # OCI image is built from the unmodified stage structure above.
    smoke = work/f'Dockerfile.{name}.import-smoke'
    smoke_content = content.replace(
        'FROM ${PYTHON_BASE_IMAGE}',
        'FROM ${PYTHON_BASE_IMAGE} AS agentium_release',
        1,
    )
    smoke_content += '''

FROM agentium_release AS agentium_import_smoke
RUN --network=none --mount=type=secret,id=image_import_smoke,mode=0444,required=true \\
    python /run/secrets/image_import_smoke
'''
    smoke.write_text(smoke_content)
    Path(str(smoke)+'.dockerignore').write_text(Path(str(original)+'.dockerignore').read_text())
