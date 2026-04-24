"""Tool schemas for the Canva plugin."""

CANVA_GET_CAPABILITIES = {
    "name": "canva_get_capabilities",
    "description": "Check Canva account capabilities such as resize, brand template access, and autofill access before planning a design workflow.",
    "parameters": {"type": "object", "properties": {}},
}

CANVA_CREATE_DESIGN = {
    "name": "canva_create_design",
    "description": "Create a new Canva design from a supported Canva preset or custom dimensions. Friendly presets like instagram-post are translated into custom dimensions.",
    "parameters": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "preset_name": {"type": "string"},
            "width": {"type": "integer"},
            "height": {"type": "integer"},
            "asset_id": {"type": "string"},
            "allow_blank": {"type": "boolean"},
        },
    },
}

CANVA_LIST_DESIGNS = {
    "name": "canva_list_designs",
    "description": "List or search Canva designs for the authenticated user.",
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "ownership": {"type": "string"},
            "sort_by": {"type": "string"},
            "limit": {"type": "integer"},
            "continuation": {"type": "string"},
        },
    },
}

CANVA_GET_DESIGN = {
    "name": "canva_get_design",
    "description": "Get Canva design metadata, page info, and export formats.",
    "parameters": {
        "type": "object",
        "properties": {
            "design_id": {"type": "string"},
            "include_pages": {"type": "boolean"},
            "include_export_formats": {"type": "boolean"},
        },
        "required": ["design_id"],
    },
}

CANVA_UPDATE_DESIGN = {
    "name": "canva_update_design",
    "description": "Create a resized copy of an existing Canva design.",
    "parameters": {
        "type": "object",
        "properties": {
            "design_id": {"type": "string"},
            "preset_name": {"type": "string"},
            "width": {"type": "integer"},
            "height": {"type": "integer"},
        },
        "required": ["design_id"],
    },
}

CANVA_EXPORT_DESIGN = {
    "name": "canva_export_design",
    "description": "Export a Canva design and download the files into /workspace/canva/.",
    "parameters": {
        "type": "object",
        "properties": {
            "design_id": {"type": "string"},
            "format_type": {"type": "string"},
            "pages": {"type": "array", "items": {"type": "integer"}},
            "width": {"type": "integer"},
            "height": {"type": "integer"},
            "quality": {"oneOf": [{"type": "integer"}, {"type": "string"}]},
            "export_quality": {"type": "string"},
            "transparent_background": {"type": "boolean"},
            "lossless": {"type": "boolean"},
            "as_single_image": {"type": "boolean"},
            "filename_prefix": {"type": "string"},
        },
        "required": ["design_id", "format_type"],
    },
}

CANVA_LIST_EXPORT_FORMATS = {
    "name": "canva_list_export_formats",
    "description": "List the available export formats for a Canva design.",
    "parameters": {
        "type": "object",
        "properties": {"design_id": {"type": "string"}},
        "required": ["design_id"],
    },
}

CANVA_UPLOAD_ASSET = {
    "name": "canva_upload_asset",
    "description": "Upload a local image or video file to Canva so it can be used in a design or autofill workflow.",
    "parameters": {
        "type": "object",
        "properties": {
            "file_path": {"type": "string"},
            "name": {"type": "string"},
            "tags": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["file_path"],
    },
}

CANVA_UPLOAD_ASSET_FROM_URL = {
    "name": "canva_upload_asset_from_url",
    "description": "Import an image or video into Canva from a public URL for use in later design steps.",
    "parameters": {
        "type": "object",
        "properties": {
            "url": {"type": "string"},
            "name": {"type": "string"},
            "tags": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["url", "name"],
    },
}

CANVA_LIST_LOCAL_ASSETS = {
    "name": "canva_list_local_assets",
    "description": "List recent local Canva-ready assets already staged under /workspace/canva/files/inbox/ so the agent can reuse them instead of relying on Discord CDN URLs.",
    "parameters": {
        "type": "object",
        "properties": {
            "limit": {"type": "integer"},
        },
    },
}

CANVA_LIST_BRAND_TEMPLATES = {
    "name": "canva_list_brand_templates",
    "description": "List Canva brand templates, especially templates with autofill datasets for high-quality automated design generation.",
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "ownership": {"type": "string"},
            "dataset": {"type": "string"},
            "sort_by": {"type": "string"},
            "limit": {"type": "integer"},
            "continuation": {"type": "string"},
        },
    },
}

CANVA_GET_BRAND_TEMPLATE_DATASET = {
    "name": "canva_get_brand_template_dataset",
    "description": "Inspect the autofillable fields of a brand template before generating a populated design.",
    "parameters": {
        "type": "object",
        "properties": {
            "brand_template_id": {"type": "string"},
        },
        "required": ["brand_template_id"],
    },
}

CANVA_AUTOFILL_DESIGN = {
    "name": "canva_autofill_design",
    "description": "Generate a Canva design from a brand template using a structured data payload. Prefer this over blank design creation for polished outputs.",
    "parameters": {
        "type": "object",
        "properties": {
            "brand_template_id": {"type": "string"},
            "data": {"type": "object", "additionalProperties": True},
            "title": {"type": "string"},
        },
        "required": ["brand_template_id", "data"],
    },
}

CANVA_GET_ASSET = {
    "name": "canva_get_asset",
    "description": "Read Canva asset metadata for an uploaded image or video.",
    "parameters": {
        "type": "object",
        "properties": {"asset_id": {"type": "string"}},
        "required": ["asset_id"],
    },
}

CANVA_UPDATE_ASSET = {
    "name": "canva_update_asset",
    "description": "Update the name and/or tags for a Canva asset.",
    "parameters": {
        "type": "object",
        "properties": {
            "asset_id": {"type": "string"},
            "name": {"type": "string"},
            "tags": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["asset_id"],
    },
}

CANVA_DELETE_ASSET = {
    "name": "canva_delete_asset",
    "description": "Delete a Canva asset from the user's Projects.",
    "parameters": {
        "type": "object",
        "properties": {"asset_id": {"type": "string"}},
        "required": ["asset_id"],
    },
}

CANVA_NORMALIZE_DESIGN_BRIEF = {
    "name": "canva_normalize_design_brief",
    "description": "Turn a messy design request into a structured Canva brief with objective, format, audience, tone, copy, assets, and export target.",
    "parameters": {
        "type": "object",
        "properties": {
            "prompt": {"type": "string"},
            "format_hint": {"type": "string"},
            "asset_paths": {"type": "array", "items": {"type": "string"}},
            "asset_urls": {"type": "array", "items": {"type": "string"}},
            "asset_id": {"type": "string"},
            "brand_template_id": {"type": "string"},
            "allow_blank": {"type": "boolean"},
        },
        "required": ["prompt"],
    },
}

CANVA_QA_DESIGN_BRIEF = {
    "name": "canva_qa_design_brief",
    "description": "Score whether a structured Canva brief is ready for execution or still underspecified.",
    "parameters": {
        "type": "object",
        "properties": {
            "brief": {"type": "object", "additionalProperties": True},
        },
        "required": ["brief"],
    },
}

CANVA_MAKE_POSTER_FROM_ASSET = {
    "name": "canva_make_poster_from_asset",
    "description": "High-level playbook that prepares the best Canva poster workflow from one primary asset and a structured brief.",
    "parameters": {
        "type": "object",
        "properties": {
            "headline": {"type": "string"},
            "support_text": {"type": "string"},
            "cta": {"type": "string"},
            "tone": {"type": "string"},
            "audience": {"type": "string"},
            "asset_id": {"type": "string"},
            "asset_path": {"type": "string"},
            "asset_url": {"type": "string"},
            "brand_template_id": {"type": "string"},
            "title": {"type": "string"},
            "width": {"type": "integer"},
            "height": {"type": "integer"},
            "export_format": {"type": "string"},
            "filename_prefix": {"type": "string"},
            "allow_blank": {"type": "boolean"},
        },
    },
}

CANVA_MAKE_SOCIAL_POST = {
    "name": "canva_make_social_post",
    "description": "High-level playbook for an asset-led Canva social post.",
    "parameters": {
        "type": "object",
        "properties": {
            "headline": {"type": "string"},
            "support_text": {"type": "string"},
            "cta": {"type": "string"},
            "tone": {"type": "string"},
            "audience": {"type": "string"},
            "asset_id": {"type": "string"},
            "asset_path": {"type": "string"},
            "asset_url": {"type": "string"},
            "brand_template_id": {"type": "string"},
            "title": {"type": "string"},
            "width": {"type": "integer"},
            "height": {"type": "integer"},
            "export_format": {"type": "string"},
            "filename_prefix": {"type": "string"},
            "allow_blank": {"type": "boolean"},
        },
    },
}

CANVA_MAKE_COVER_FROM_IMAGE = {
    "name": "canva_make_cover_from_image",
    "description": "High-level playbook for a presentation or document cover built from one hero image.",
    "parameters": {
        "type": "object",
        "properties": {
            "headline": {"type": "string"},
            "support_text": {"type": "string"},
            "tone": {"type": "string"},
            "audience": {"type": "string"},
            "asset_id": {"type": "string"},
            "asset_path": {"type": "string"},
            "asset_url": {"type": "string"},
            "brand_template_id": {"type": "string"},
            "title": {"type": "string"},
            "width": {"type": "integer"},
            "height": {"type": "integer"},
            "export_format": {"type": "string"},
            "filename_prefix": {"type": "string"},
            "allow_blank": {"type": "boolean"},
        },
    },
}

CANVA_CREATE_COMMENT_THREAD = {
    "name": "canva_create_comment_thread",
    "description": "Create a top-level Canva comment thread on a design for review, approval, or handoff notes.",
    "parameters": {
        "type": "object",
        "properties": {
            "design_id": {"type": "string"},
            "message_plaintext": {"type": "string"},
            "assignee_id": {"type": "string"},
        },
        "required": ["design_id", "message_plaintext"],
    },
}

CANVA_GET_COMMENT_THREAD = {
    "name": "canva_get_comment_thread",
    "description": "Read a Canva comment thread and its metadata from a design.",
    "parameters": {
        "type": "object",
        "properties": {
            "design_id": {"type": "string"},
            "thread_id": {"type": "string"},
        },
        "required": ["design_id", "thread_id"],
    },
}

CANVA_CREATE_COMMENT_REPLY = {
    "name": "canva_create_comment_reply",
    "description": "Reply to an existing Canva comment thread on a design.",
    "parameters": {
        "type": "object",
        "properties": {
            "design_id": {"type": "string"},
            "thread_id": {"type": "string"},
            "message_plaintext": {"type": "string"},
        },
        "required": ["design_id", "thread_id", "message_plaintext"],
    },
}

CANVA_LIST_COMMENT_REPLIES = {
    "name": "canva_list_comment_replies",
    "description": "List replies inside a Canva comment thread.",
    "parameters": {
        "type": "object",
        "properties": {
            "design_id": {"type": "string"},
            "thread_id": {"type": "string"},
            "continuation": {"type": "string"},
        },
        "required": ["design_id", "thread_id"],
    },
}
