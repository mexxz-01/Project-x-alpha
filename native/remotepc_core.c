/**
 * Project-X-Nano Native C/C++ Acceleration Engine Implementation
 * Ultra low-latency C implementation for Windows 10/11 x64 & x86
 */

#define REMOTEPC_EXPORTS
#include "remotepc_core.h"

#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <shellscalingapi.h>
#include <timeapi.h>

#pragma comment(lib, "user32.lib")
#pragma comment(lib, "gdi32.lib")
#pragma comment(lib, "kernel32.lib")
#pragma comment(lib, "winmm.lib")
#pragma comment(lib, "shcore.lib")

static HDC g_hdcScreen = NULL;
static HDC g_hdcMem = NULL;
static HBITMAP g_hBitmap = NULL;
static int g_cachedWidth = 0;
static int g_cachedHeight = 0;
static CRITICAL_SECTION g_screenLock;
static int g_isInitialized = 0;

REMOTEPC_API int RemotePC_Init(void) {
    if (g_isInitialized) return 1;

    /* Set per-monitor DPI awareness v2 */
    HMODULE hShcore = LoadLibraryA("Shcore.dll");
    if (hShcore) {
        typedef HRESULT(WINAPI *SetProcessDpiAwareness_t)(PROCESS_DPI_AWARENESS);
        SetProcessDpiAwareness_t pSetDpi = (SetProcessDpiAwareness_t)GetProcAddress(hShcore, "SetProcessDpiAwareness");
        if (pSetDpi) {
            pSetDpi(PROCESS_PER_MONITOR_DPI_AWARE);
        }
        FreeLibrary(hShcore);
    }

    /* Set 1ms multimedia timer resolution for smooth frame delivery */
    timeBeginPeriod(1);

    InitializeCriticalSection(&g_screenLock);
    g_isInitialized = 1;
    return 1;
}

REMOTEPC_API void RemotePC_Shutdown(void) {
    if (!g_isInitialized) return;

    EnterCriticalSection(&g_screenLock);
    if (g_hBitmap) { DeleteObject(g_hBitmap); g_hBitmap = NULL; }
    if (g_hdcMem) { DeleteDC(g_hdcMem); g_hdcMem = NULL; }
    if (g_hdcScreen) { ReleaseDC(NULL, g_hdcScreen); g_hdcScreen = NULL; }
    g_cachedWidth = 0;
    g_cachedHeight = 0;
    LeaveCriticalSection(&g_screenLock);

    DeleteCriticalSection(&g_screenLock);
    timeEndPeriod(1);
    g_isInitialized = 0;
}

REMOTEPC_API void RemotePC_GetScreenSize(int* width, int* height) {
    if (width) *width = GetSystemMetrics(SM_CXSCREEN);
    if (height) *height = GetSystemMetrics(SM_CYSCREEN);
}

REMOTEPC_API int RemotePC_CaptureScreenBGRA(unsigned char* buf, int max_len, int* out_w, int* out_h) {
    if (!buf) return 0;
    if (!g_isInitialized) RemotePC_Init();

    int w = GetSystemMetrics(SM_CXSCREEN);
    int h = GetSystemMetrics(SM_CYSCREEN);
    int req_bytes = w * h * 4;

    if (max_len < req_bytes) return 0;

    EnterCriticalSection(&g_screenLock);

    if (!g_hdcScreen) {
        g_hdcScreen = GetDC(NULL);
    }
    if (!g_hdcMem) {
        g_hdcMem = CreateCompatibleDC(g_hdcScreen);
    }

    /* Reallocate bitmap if screen dimensions changed */
    if (!g_hBitmap || g_cachedWidth != w || g_cachedHeight != h) {
        if (g_hBitmap) DeleteObject(g_hBitmap);
        g_hBitmap = CreateCompatibleBitmap(g_hdcScreen, w, h);
        SelectObject(g_hdcMem, g_hBitmap);
        g_cachedWidth = w;
        g_cachedHeight = h;
    }

    /* Hardware BitBlt capture */
    BOOL bltOk = BitBlt(g_hdcMem, 0, 0, w, h, g_hdcScreen, 0, 0, SRCCOPY | CAPTUREBLT);
    if (!bltOk) {
        LeaveCriticalSection(&g_screenLock);
        return 0;
    }

    /* Read DIB bits directly into caller-supplied buffer */
    BITMAPINFO bmi;
    ZeroMemory(&bmi, sizeof(BITMAPINFO));
    bmi.bmiHeader.biSize = sizeof(BITMAPINFOHEADER);
    bmi.bmiHeader.biWidth = w;
    bmi.bmiHeader.biHeight = -h; /* Top-down DIB */
    bmi.bmiHeader.biPlanes = 1;
    bmi.bmiHeader.biBitCount = 32;
    bmi.bmiHeader.biCompression = BI_RGB;

    int scanlines = GetDIBits(g_hdcMem, g_hBitmap, 0, h, buf, &bmi, DIB_RGB_COLORS);
    LeaveCriticalSection(&g_screenLock);

    if (scanlines == 0) return 0;

    if (out_w) *out_w = w;
    if (out_h) *out_h = h;
    return 1;
}

REMOTEPC_API int RemotePC_MouseMoveRelative(int dx, int dy) {
    /* Send mouse movement via mouse_event with instant kernel dispatch */
    mouse_event(MOUSEEVENTF_MOVE, (DWORD)dx, (DWORD)dy, 0, 0);
    return 1;
}

REMOTEPC_API int RemotePC_MouseClickAbsolute(double x_norm, double y_norm, int right_click, int double_click) {
    int screen_w = GetSystemMetrics(SM_CXSCREEN);
    int screen_h = GetSystemMetrics(SM_CYSCREEN);

    if (x_norm < 0.0) x_norm = 0.0;
    if (x_norm > 1.0) x_norm = 1.0;
    if (y_norm < 0.0) y_norm = 0.0;
    if (y_norm > 1.0) y_norm = 1.0;

    int target_x = (int)(x_norm * (screen_w - 1));
    int target_y = (int)(y_norm * (screen_h - 1));

    SetCursorPos(target_x, target_y);

    DWORD downFlag = right_click ? MOUSEEVENTF_RIGHTDOWN : MOUSEEVENTF_LEFTDOWN;
    DWORD upFlag   = right_click ? MOUSEEVENTF_RIGHTUP   : MOUSEEVENTF_LEFTUP;

    mouse_event(downFlag, 0, 0, 0, 0);
    mouse_event(upFlag, 0, 0, 0, 0);

    if (double_click) {
        Sleep(40);
        mouse_event(downFlag, 0, 0, 0, 0);
        mouse_event(upFlag, 0, 0, 0, 0);
    }

    return 1;
}

REMOTEPC_API int RemotePC_MouseScroll(int lines) {
    mouse_event(MOUSEEVENTF_WHEEL, 0, 0, (DWORD)(lines * WHEEL_DELTA), 0);
    return 1;
}

REMOTEPC_API int RemotePC_KeyPress(unsigned short vk_code, int key_up) {
    DWORD flags = key_up ? KEYEVENTF_KEYUP : 0;
    keybd_event((BYTE)vk_code, 0, flags, 0);
    return 1;
}

REMOTEPC_API int RemotePC_GetMemoryStats(unsigned long long* total_bytes, unsigned long long* avail_bytes, int* load_pct) {
    MEMORYSTATUSEX mem;
    mem.dwLength = sizeof(MEMORYSTATUSEX);
    if (!GlobalMemoryStatusEx(&mem)) return 0;

    if (total_bytes) *total_bytes = mem.ullTotalPhys;
    if (avail_bytes) *avail_bytes = mem.ullAvailPhys;
    if (load_pct) *load_pct = (int)mem.dwMemoryLoad;
    return 1;
}

REMOTEPC_API int RemotePC_LockWorkstation(void) {
    return LockWorkStation() ? 1 : 0;
}

REMOTEPC_API int RemotePC_Suspend(int hibernate) {
    HMODULE hPowrprof = LoadLibraryA("powrprof.dll");
    if (!hPowrprof) return 0;

    typedef BOOLEAN(WINAPI *SetSuspendState_t)(BOOLEAN, BOOLEAN, BOOLEAN);
    SetSuspendState_t pSetSuspendState = (SetSuspendState_t)GetProcAddress(hPowrprof, "SetSuspendState");
    int ok = 0;
    if (pSetSuspendState) {
        ok = pSetSuspendState((BOOLEAN)hibernate, FALSE, FALSE) ? 1 : 0;
    }
    FreeLibrary(hPowrprof);
    return ok;
}

#else
/* Linux / POSIX stubs if needed */
REMOTEPC_API int RemotePC_Init(void) { return 1; }
REMOTEPC_API void RemotePC_Shutdown(void) {}
REMOTEPC_API void RemotePC_GetScreenSize(int* width, int* height) { if (width) *width = 0; if (height) *height = 0; }
REMOTEPC_API int RemotePC_CaptureScreenBGRA(unsigned char* buf, int max_len, int* out_w, int* out_h) { return 0; }
REMOTEPC_API int RemotePC_MouseMoveRelative(int dx, int dy) { return 0; }
REMOTEPC_API int RemotePC_MouseClickAbsolute(double x_norm, double y_norm, int right_click, int double_click) { return 0; }
REMOTEPC_API int RemotePC_MouseScroll(int lines) { return 0; }
REMOTEPC_API int RemotePC_KeyPress(unsigned short vk_code, int key_up) { return 0; }
REMOTEPC_API int RemotePC_GetMemoryStats(unsigned long long* total, unsigned long long* avail, int* load) { return 0; }
REMOTEPC_API int RemotePC_LockWorkstation(void) { return 0; }
REMOTEPC_API int RemotePC_Suspend(int hibernate) { return 0; }
#endif
