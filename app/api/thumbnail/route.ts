import { NextResponse } from 'next/server';
import { randomUUID } from 'node:crypto';
import { mkdir, writeFile, readFile } from 'node:fs/promises';
import path from 'node:path';
import { spawn } from 'node:child_process';
export const runtime='nodejs';
export async function POST(req:Request){
 const f=(await req.formData()).get('file');
 if(!(f instanceof File)) return NextResponse.json({error:'FILE_REQUIRED'},{status:400});
 const dir='/tmp/clipforge-thumbnails'; await mkdir(dir,{recursive:true});
 const id=randomUUID(), input=path.join(dir,id+'.mp4'), output=path.join(dir,id+'.jpg');
 await writeFile(input,Buffer.from(await f.arrayBuffer()));
 await new Promise<void>((resolve,reject)=>{const p=spawn('ffmpeg',['-y','-ss','00:00:02','-i',input,'-frames:v','1','-vf','scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2','-q:v','3',output]);p.on('close',c=>c===0?resolve():reject(new Error('thumbnail extraction failed')))});
 return new NextResponse(await readFile(output),{headers:{'Content-Type':'image/jpeg','Content-Disposition':`attachment; filename="thumbnail-${id}.jpg"`}});
}
