import { NodeIO } from '@gltf-transform/core';
// 1. Voeg 'cloneDocument' toe aan de importlijst hieronder:
import { simplify, resample, textureCompress, prune, dedup, draco, cloneDocument } from '@gltf-transform/functions';
import { ALL_EXTENSIONS } from '@gltf-transform/extensions';
import { MeshoptSimplifier } from 'meshoptimizer';
import draco3d from 'draco3d';
import sharp from 'sharp'; 
import fs from 'fs';
import path from 'path';

// Configuratie
const INPUT_DIR = './raw_assets';
const OUTPUT_DIR = './assets';

// Kwaliteitsinstellingen
const TIERS = {
    ultra:  { ratio: 1.0, texSize: 4096, draco: false }, 
    high:   { ratio: 0.8, texSize: 2048, draco: true },  
    medium: { ratio: 0.5, texSize: 1024, draco: true },  
    low:    { ratio: 0.2, texSize: 512,  draco: true }   
};

async function main() {
    const io = new NodeIO()
        .registerExtensions(ALL_EXTENSIONS)
        .registerDependencies({
            'draco3d.decoder': await draco3d.createDecoderModule(),
            'draco3d.encoder': await draco3d.createEncoderModule(),
        });

    if (!fs.existsSync(OUTPUT_DIR)) fs.mkdirSync(OUTPUT_DIR, { recursive: true });

    console.log("🚀 Starting Multi-Tier Asset Optimization...");

    const files = fs.readdirSync(INPUT_DIR).filter(f => f.endsWith('.glb'));

    for (const file of files) {
        const inputPath = path.join(INPUT_DIR, file);
        const baseName = file.replace('.glb', '');
        console.log(`\n📦 Processing: ${file}`);

        const originalDoc = await io.read(inputPath);

        // STAP 1: Algemene opschoning
        await originalDoc.transform(
            resample({ tolerance: 0.001 }),
            prune(),
            dedup()
        );

        // Genereer elke tier
        for (const [tierName, settings] of Object.entries(TIERS)) {
            console.log(`   ⚙️ Generating [${tierName}]...`);
            
            // 2. GEBRUIK HIER DE NIEUWE FUNCTIE:
            const doc = await cloneDocument(originalDoc);

            const transforms = [];

            // Texture Compressie
            transforms.push(
                textureCompress({
                    encoder: sharp,
                    targetFormat: 'webp',
                    resize: [settings.texSize, settings.texSize], 
                    quality: tierName === 'ultra' ? 100 : 80
                })
            );

            // Geometry Simplify
            if (settings.ratio < 1.0) {
                transforms.push(
                    simplify({ simplifier: MeshoptSimplifier, ratio: settings.ratio, error: 0.01 })
                );
            }

            // Draco Compressie
            if (settings.draco) {
                transforms.push(
                    draco({ compressionLevel: 7 })
                );
            }

            await doc.transform(...transforms);

            const outName = `${baseName}_${tierName}.glb`;
            await io.write(path.join(OUTPUT_DIR, outName), doc);
            console.log(`      ✅ Saved ${outName}`);
        }
    }
}

main().catch(err => console.error(err));