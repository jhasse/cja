#include <stdio.h>

#ifdef _WIN32
#include <windows.h>
#endif

static int app_main(void) {
#ifdef _WIN32
    MessageBoxA(NULL, "Hello from win32_executable example", "Hello", MB_OK);
#endif
    printf("Hello from win32_executable example\n");
    return 0;
}

/* Console builds (e.g. Debug) use main. */
int main(void) {
    return app_main();
}

#ifdef _WIN32
/* GUI builds (WIN32_EXECUTABLE) use WinMain under the MSVC CRT. */
int WINAPI WinMain(HINSTANCE hInstance, HINSTANCE hPrevInstance, LPSTR lpCmdLine,
                   int nCmdShow) {
    (void)hInstance;
    (void)hPrevInstance;
    (void)lpCmdLine;
    (void)nCmdShow;
    return app_main();
}
#endif
