# BPMN AS-IS / CIBLE dataset

The dataset contains deterministic AS-IS inputs paired with optimized CIBLE references. CIBLE files are immutable evaluation ground truth. The manifest is never supplied to Qwen.

### Approvisionnement par gré à gré / Mise en place

AS-IS: `data/bpmn/as_is/Approvisionnement Gré à gré&Mise en place.bpmn`  
CIBLE: `data/bpmn/cible/Approvisionnement Gré à gré&Mise en place.bpmn`

Deliberate differences:

1. GED archival of the market-decision minutes is missing (control insertion).
2. A redundant contract-file e-mail precedes the contract subprocess (redundancy removal).
3. The article-record task uses a legacy SI label (rename).

### Préparation et traitement des commandes d’achat — Appel d'offres

AS-IS: `data/bpmn/as_is/Approvisionnement par Appel d'offres.bpmn`  
CIBLE: `data/bpmn/cible/Approvisionnement par Appel d'offres.bpmn`

Deliberate differences:

1. GED archival of the specifications is missing (control insertion).
2. The comparison table is sent manually before supplier selection (redundancy removal).
3. Financial import uses a legacy label (rename).

Only process `Id_1a378fa6-28f6-4313-b53f-35ddd52a25a7` is degraded; other variants remain semantically unchanged.

### Détermination des besoins d’approvisionnement

AS-IS: `data/bpmn/as_is/Détermination des besoins d'approvisionnement.bpmn`  
CIBLE: `data/bpmn/cible/Détermination des besoins d'approvisionnement.bpmn`

Deliberate differences:

1. Automated stock coverage becomes an Excel calculation sequence (automation).
2. Financial simulation analysis is missing (cross-lane control insertion).
3. Simulations are redundantly copied into a tracking file (redundancy removal).

### Gestion des contrats

AS-IS: `data/bpmn/as_is/Gestion des contrats.bpmn`  
CIBLE: `data/bpmn/cible/Gestion des contrats.bpmn`

Deliberate differences:

1. Signed-contract retrieval becomes a manual portal sequence (automation).
2. Legal contract review is missing (cross-lane control insertion).
3. Draft receipt uses a legacy file-oriented label (rename).

### Lancement des commandes

AS-IS: `data/bpmn/as_is/Lancement des commandes.bpmn`  
CIBLE: `data/bpmn/cible/Lancement des commandes.bpmn`

Deliberate differences:

1. Automatic delivery-plan suggestion becomes a spreadsheet sequence (automation).
2. A redundant manual transmission precedes the Transit call activity (redundancy removal).
3. Order dispatch uses a legacy attachment-oriented label (rename).

### Suivi des commandes

AS-IS: `data/bpmn/as_is/Suivi des commandes.bpmn`  
CIBLE: `data/bpmn/cible/Suivi des commandes.bpmn`

Deliberate differences:

1. Automatic open-order reporting becomes a manual consolidation sequence (automation).
2. General-management approval of the reminder letter is missing (control insertion).
3. Supplier reminders are redundantly logged in a shared file (redundancy removal).

## Rebuilding

```powershell
uv run python scripts/build_as_is_dataset.py
```

The generator always rebuilds AS-IS files from CIBLE, validates both sides, checks process isolation, verifies CIBLE checksums, and rewrites `dataset_manifest.json` deterministically.
