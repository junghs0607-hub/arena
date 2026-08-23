import {NextResponse} from 'next/server';
import {videoSources} from '../../../drizzle/schema';
import {db} from '../../../lib/db';
export async function GET(){try{return NextResponse.json(await db.select().from(videoSources))}catch{return NextResponse.json({error:'DATABASE_UNAVAILABLE',message:'Set DATABASE_URL and run migrations.'},{status:503})}}
export async function POST(req:Request){const body=await req.json();if(!body.title||!body.licenseConfirmed)return NextResponse.json({error:'TITLE_AND_LICENSE_REQUIRED'},{status:400});try{const [source]=await db.insert(videoSources).values({title:body.title,sourceUrl:body.sourceUrl,fileKey:body.fileKey,licenseConfirmed:true,licenseNote:body.licenseNote,status:'pending'}).returning();return NextResponse.json(source,{status:201})}catch{return NextResponse.json({error:'DATABASE_UNAVAILABLE'},{status:503})}}
