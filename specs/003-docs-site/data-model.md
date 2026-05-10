# Data Model: User-Facing Documentation Site

**Feature Branch**: `003-docs-site`
**Date**: 2026-04-03

## Overview

This feature has no database entities. The "data model" is the content structure — Markdown files organized into sections that Docusaurus renders as a static site.

## Content Entities

### Documentation Page

A single Markdown/MDX file with frontmatter metadata.

**Attributes**:
- `title` — Page title (displayed in sidebar and browser tab)
- `sidebar_position` — Numeric ordering within its section
- `sidebar_label` — Optional short label for the sidebar (defaults to title)
- `description` — SEO/meta description
- `tags` — Optional categorization tags
- `slug` — Optional custom URL path

**Example frontmatter**:
```yaml
---
title: Installing on EKS
sidebar_position: 1
description: Step-by-step guide to deploying Styrmin on Amazon EKS
tags: [installation, eks, aws]
---
```

### Documentation Section (Category)

A directory with a `_category_.json` metadata file defining the section's sidebar behavior.

**Attributes**:
- `label` — Section display name
- `position` — Numeric ordering among sibling sections
- `collapsed` — Whether the section starts collapsed in the sidebar
- `link.type` — Whether the section itself is a clickable page (`doc` or `generated-index`)

**Example `_category_.json`**:
```json
{
  "label": "Installation",
  "position": 2,
  "collapsed": false,
  "link": {
    "type": "generated-index",
    "description": "Installation guides for supported Kubernetes platforms"
  }
}
```

## Content Hierarchy

```text
docs/docs/
├── getting-started/          # Section: Getting Started
│   ├── _category_.json
│   ├── overview.md           # What is Styrmin, core concepts
│   └── quickstart.md         # Minimal path to running instance
├── installation/             # Section: Installation
│   ├── _category_.json
│   ├── prerequisites.md      # Common prerequisites
│   ├── eks.md                # EKS-specific guide
│   ├── gke.md                # GKE-specific guide
│   ├── aks.md                # AKS-specific guide
│   ├── k3s.md                # k3s-specific guide
│   └── kubeadm.md            # kubeadm-specific guide
├── drivers/                  # Section: Application Drivers
│   ├── _category_.json
│   ├── what-is-a-driver.md   # Conceptual overview
│   ├── creating-a-driver.md  # Step-by-step creation guide
│   ├── specification.md      # Field reference (from DRIVERS.md)
│   └── example-walkthrough.md # Complete example (from driver/examples/)
└── reference/                # Section: Reference (optional, future)
    └── _category_.json
```

## Relationships

- Each **Page** belongs to exactly one **Section** (its parent directory)
- **Sections** can be nested (subdirectories), but the initial structure is flat (one level of sections)
- The **sidebar** is auto-generated from the directory structure and metadata files
- **Driver documentation** pages reference concepts from the **Getting Started** section via internal links
