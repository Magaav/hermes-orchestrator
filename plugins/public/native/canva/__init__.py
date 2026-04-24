"""Hermes-native Canva plugin."""

from __future__ import annotations

from pathlib import Path

from . import cli, hooks, schemas, tools


def register(ctx):
    ctx.register_hook(
        "pre_llm_call",
        hooks.inject_canva_turn_context,
    )
    ctx.register_tool(
        name="canva_get_capabilities",
        toolset="canva",
        schema=schemas.CANVA_GET_CAPABILITIES,
        handler=tools.canva_get_capabilities,
        description="Check which Canva premium capabilities are available for this user.",
    )
    ctx.register_tool(
        name="canva_create_design",
        toolset="canva",
        schema=schemas.CANVA_CREATE_DESIGN,
        handler=tools.canva_create_design,
        description="Create a Canva design from a preset or custom dimensions.",
    )
    ctx.register_tool(
        name="canva_list_designs",
        toolset="canva",
        schema=schemas.CANVA_LIST_DESIGNS,
        handler=tools.canva_list_designs,
        description="List or search Canva designs available to the authenticated user.",
    )
    ctx.register_tool(
        name="canva_get_design",
        toolset="canva",
        schema=schemas.CANVA_GET_DESIGN,
        handler=tools.canva_get_design,
        description="Get Canva design metadata, pages, and export formats.",
    )
    ctx.register_tool(
        name="canva_update_design",
        toolset="canva",
        schema=schemas.CANVA_UPDATE_DESIGN,
        handler=tools.canva_update_design,
        description="Create a resized copy of an existing Canva design.",
    )
    ctx.register_tool(
        name="canva_export_design",
        toolset="canva",
        schema=schemas.CANVA_EXPORT_DESIGN,
        handler=tools.canva_export_design,
        description="Export a Canva design and download the result to /workspace/canva/.",
    )
    ctx.register_tool(
        name="canva_list_export_formats",
        toolset="canva",
        schema=schemas.CANVA_LIST_EXPORT_FORMATS,
        handler=tools.canva_list_export_formats,
        description="List the export formats available for a Canva design.",
    )
    ctx.register_tool(
        name="canva_upload_asset",
        toolset="canva",
        schema=schemas.CANVA_UPLOAD_ASSET,
        handler=tools.canva_upload_asset,
        description="Upload a local image or video asset into Canva.",
    )
    ctx.register_tool(
        name="canva_upload_asset_from_url",
        toolset="canva",
        schema=schemas.CANVA_UPLOAD_ASSET_FROM_URL,
        handler=tools.canva_upload_asset_from_url,
        description="Import an asset into Canva from a public URL.",
    )
    ctx.register_tool(
        name="canva_list_local_assets",
        toolset="canva",
        schema=schemas.CANVA_LIST_LOCAL_ASSETS,
        handler=tools.canva_list_local_assets,
        description="List recent local Canva-ready assets staged in /workspace/canva/files/inbox/.",
    )
    ctx.register_tool(
        name="canva_get_asset",
        toolset="canva",
        schema=schemas.CANVA_GET_ASSET,
        handler=tools.canva_get_asset,
        description="Read Canva asset metadata for an uploaded image or video.",
    )
    ctx.register_tool(
        name="canva_update_asset",
        toolset="canva",
        schema=schemas.CANVA_UPDATE_ASSET,
        handler=tools.canva_update_asset,
        description="Update the name and tags for a Canva asset.",
    )
    ctx.register_tool(
        name="canva_delete_asset",
        toolset="canva",
        schema=schemas.CANVA_DELETE_ASSET,
        handler=tools.canva_delete_asset,
        description="Delete a Canva asset from the user's Projects.",
    )
    ctx.register_tool(
        name="canva_list_brand_templates",
        toolset="canva",
        schema=schemas.CANVA_LIST_BRAND_TEMPLATES,
        handler=tools.canva_list_brand_templates,
        description="List Canva brand templates that can be used for autofill workflows.",
    )
    ctx.register_tool(
        name="canva_get_brand_template_dataset",
        toolset="canva",
        schema=schemas.CANVA_GET_BRAND_TEMPLATE_DATASET,
        handler=tools.canva_get_brand_template_dataset,
        description="Inspect the autofillable fields for a Canva brand template.",
    )
    ctx.register_tool(
        name="canva_autofill_design",
        toolset="canva",
        schema=schemas.CANVA_AUTOFILL_DESIGN,
        handler=tools.canva_autofill_design,
        description="Generate a populated Canva design from a brand template and input data.",
    )
    ctx.register_tool(
        name="canva_normalize_design_brief",
        toolset="canva",
        schema=schemas.CANVA_NORMALIZE_DESIGN_BRIEF,
        handler=tools.canva_normalize_design_brief,
        description="Convert a freeform design ask into a structured Canva brief.",
    )
    ctx.register_tool(
        name="canva_qa_design_brief",
        toolset="canva",
        schema=schemas.CANVA_QA_DESIGN_BRIEF,
        handler=tools.canva_qa_design_brief,
        description="Score whether a Canva brief is ready for execution.",
    )
    ctx.register_tool(
        name="canva_make_poster_from_asset",
        toolset="canva",
        schema=schemas.CANVA_MAKE_POSTER_FROM_ASSET,
        handler=tools.canva_make_poster_from_asset,
        description="High-level Canva poster workflow from one primary asset.",
    )
    ctx.register_tool(
        name="canva_make_social_post",
        toolset="canva",
        schema=schemas.CANVA_MAKE_SOCIAL_POST,
        handler=tools.canva_make_social_post,
        description="High-level Canva social-post workflow from one primary asset.",
    )
    ctx.register_tool(
        name="canva_make_cover_from_image",
        toolset="canva",
        schema=schemas.CANVA_MAKE_COVER_FROM_IMAGE,
        handler=tools.canva_make_cover_from_image,
        description="High-level Canva cover workflow from one hero image.",
    )
    ctx.register_tool(
        name="canva_create_comment_thread",
        toolset="canva",
        schema=schemas.CANVA_CREATE_COMMENT_THREAD,
        handler=tools.canva_create_comment_thread,
        description="Create a Canva design comment thread for review or handoff notes.",
    )
    ctx.register_tool(
        name="canva_get_comment_thread",
        toolset="canva",
        schema=schemas.CANVA_GET_COMMENT_THREAD,
        handler=tools.canva_get_comment_thread,
        description="Read an existing Canva comment thread on a design.",
    )
    ctx.register_tool(
        name="canva_create_comment_reply",
        toolset="canva",
        schema=schemas.CANVA_CREATE_COMMENT_REPLY,
        handler=tools.canva_create_comment_reply,
        description="Reply to a Canva comment thread on a design.",
    )
    ctx.register_tool(
        name="canva_list_comment_replies",
        toolset="canva",
        schema=schemas.CANVA_LIST_COMMENT_REPLIES,
        handler=tools.canva_list_comment_replies,
        description="List replies inside a Canva comment thread.",
    )
    ctx.register_command("canva-status", handler=cli.handle_canva_status, description="Show Canva plugin readiness and auth status.")
    ctx.register_command("canva-auth", handler=cli.handle_canva_auth, description="Validate Canva authentication and refresh-token exchange.")
    ctx.register_command("canva-export", handler=cli.handle_canva_export, description="Export a Canva design to /workspace/canva/.")
    ctx.register_command("canva-comment", handler=cli.handle_canva_comment, description="Create a Canva review comment on a design.")
    ctx.register_cli_command(
        name="canva",
        help="Manage the Canva plugin",
        setup_fn=cli.setup_cli,
        handler_fn=cli.handle_cli,
        description="Canva plugin tools and diagnostics.",
    )
    skills_dir = Path(__file__).parent / "skills"
    skill_md = skills_dir / "canva-designer" / "SKILL.md"
    if skill_md.exists():
        ctx.register_skill("canva-designer", skill_md, description="Prompt-efficient Canva workflow guidance.")
