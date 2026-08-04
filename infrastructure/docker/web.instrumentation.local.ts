// Docker local mode has no Sentry DSN. Keeping this entry point empty avoids
// compiling the optional monitoring bundle before the local app can respond.
export async function register() {}
