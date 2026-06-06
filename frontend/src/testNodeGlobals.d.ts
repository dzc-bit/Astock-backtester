declare module "node:fs" {
  export function existsSync(path: string): boolean;
  export function readFileSync(path: string, encoding: BufferEncoding): string;
  export function realpathSync(path: string): string;
}

declare module "node:path" {
  export function resolve(...paths: string[]): string;
}

declare module "node:url" {
  export class URL {
    constructor(input: string, base?: string | URL);
  }

  export function fileURLToPath(url: string | URL): string;
}

declare const process: {
  cwd(): string;
};

type BufferEncoding = "utf8";
