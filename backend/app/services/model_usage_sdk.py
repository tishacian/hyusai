"""Usage admission for remaining direct OpenAI SDK calls.

Unsupported multimodal bounds and requests without a finite output limit are
recorded but refused before dispatch when a blocking budget applies. This
adapter never invents an output cap or a price for an existing product route.
"""

from app.services.model_usage_transport import ProviderCall, output_limit, tracking_active


async def async_openai_chat(client, **request):
    if tracking_active():
        client = client.with_options(max_retries=0)
    with ProviderCall(
        "openai", request["model"], request, output_token_bound=output_limit(request)
    ) as call:
        response = await client.chat.completions.create(**request)
        call.observe(response)
        return response


def openai_chat(client, **request):
    if tracking_active():
        client = client.with_options(max_retries=0)
    with ProviderCall(
        "openai", request["model"], request, output_token_bound=output_limit(request)
    ) as call:
        response = client.chat.completions.create(**request)
        call.observe(response)
        return response
