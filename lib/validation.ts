import {z} from 'zod';
export const sourceInput=z.object({title:z.string().trim().min(1).max(160),sourceUrl:z.string().url().optional(),fileKey:z.string().max(500).optional(),licenseConfirmed:z.literal(true),licenseNote:z.string().max(2000).optional()}).refine(v=>v.sourceUrl||v.fileKey,{message:'sourceUrl or fileKey is required'});
export const projectInput=z.object({name:z.string().trim().min(1).max(160),sourceId:z.string().uuid(),format:z.enum(['shorts','longform']).default('shorts')});
