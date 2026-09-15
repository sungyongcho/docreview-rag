export declare const WEB_ROOT: string;
export declare function fingerprintInputs(rootDir?: string): string[];
export declare function buildFingerprint(rootDir?: string): string;
export declare function buildMetadata(options?: { rootDir?: string; now?: Date }): { fingerprint: string; builtAt: string };
