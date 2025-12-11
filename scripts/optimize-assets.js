import { NodeIO } from '@gltf-transform/core';
import { simplify, resample, textureCompress, prune, dedup, draco } from '@gltf-transform/functions';
import { ALL_EXTENSIONS } from '@gltf-transform/extensions';
import { MeshoptSimplifier } from 'meshoptimizer';
import draco3d from 'draco3d';
import sharp from 'sharp'; // Vereist: npm install sharp
import fs from 'fs';
import path from 'path';

// Configuratie
const INPUT_DIR = './raw_assets';
const OUTPUT_DIR = './assets';

// Kwaliteitsinstellingen
const TIERS = {
    ultra:  { ratio: 1.0, texSize: 4096, draco: false }, // Geen compressie, max detail
    high:   { ratio: 0.8, texSize: 2048, draco: true },  // Lichte simplify, 2k textures
    medium: { ratio: 0.5, texSize: 1024, draco: true },  // 50% poly, 1k textures
    low:    { ratio: 0.2, texSize: 512,  draco: true }   // 20% poly, 512px textures
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

        // Laad het originele bestand in het geheugen
        const originalDoc = await io.read(inputPath);

        // STAP 1: Algemene opschoning (voor alle tiers)
        // Animaties resamplen om gebakken keyframes te verwijderen
        await originalDoc.transform(
            resample({ tolerance: 0.001 }),
            prune(),
            dedup()
        );

        // Genereer elke tier
        for (const [tierName, settings] of Object.entries(TIERS)) {
            console.log(`   ⚙️ Generating [${tierName}]...`);
            
            // Clone het document zodat we het origineel niet overschrijven voor de volgende tier
            const doc = await originalDoc.clone();

            const transforms = [];

            // 1. Texture Compressie / Resizing (vereist 'sharp')
            // We converteren naar WebP voor web-standaard compressie en resizen
            transforms.push(
                textureCompress({
                    encoder: sharp,
                    targetFormat: 'webp',
                    resize: [settings.texSize, settings.texSize], 
                    quality: tierName === 'ultra' ? 100 : 80
                })
            );

            // 2. Geometry Simplify (niet op Ultra)
            if (settings.ratio < 1.0) {
                transforms.push(
                    simplify({ simplifier: MeshoptSimplifier, ratio: settings.ratio, error: 0.01 })
                );
            }

            // 3. Draco Compressie (niet op Ultra als je raw wilt, wel aanbevolen voor High/Med/Low)
            if (settings.draco) {
                transforms.push(
                    draco({ compressionLevel: 7 })
                );
            }

            // Voer alle transformaties uit
            await doc.transform(...transforms);

            // Opslaan
            const outName = `${baseName}_${tierName}.glb`;
            await io.write(path.join(OUTPUT_DIR, outName), doc);
            console.log(`      ✅ Saved ${outName}`);
        }
    }
}

main().catch(err => console.error(err));