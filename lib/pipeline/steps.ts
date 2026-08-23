import {getAIProvider} from '../ai/provider';
export type PipelineContext={projectId:string;transcript?:string;summary?:string;hook?:string;script?:string;metadata?:unknown};
export type PipelineStep={type:string;run(ctx:PipelineContext):Promise<PipelineContext>};
export const pipelineSteps:PipelineStep[]=[
 {type:'analyze_source',async run(c){const a=await getAIProvider().analyze(c.transcript||'');return {...c,summary:a.summary,hook:a.hook}}},
 {type:'script',async run(c){const s=await getAIProvider().createScript({summary:c.summary||'',hook:c.hook||'',format:'shorts'});return {...c,script:s.body}}},
 {type:'metadata',async run(c){return {...c,metadata:await getAIProvider().generateMetadata(c.script||'')}}},
 {type:'stt',async run(c){return {...c,transcript:c.transcript||''}}},
 {type:'tts',async run(c){return c}}, {type:'subtitles',async run(c){return c}}, {type:'render',async run(c){return c}}, {type:'thumbnail',async run(c){return c}}
];
export async function executePipeline(ctx:PipelineContext,types:string[]){let next=ctx;for(const type of types){const step=pipelineSteps.find(s=>s.type===type);if(step)next=await step.run(next)}return next}
