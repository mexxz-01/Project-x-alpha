/**
 * Project-X-Nano Native C/C++ Acceleration Engine Header
 * Low-latency Windows hardware hooks for screen capture, input injection,
 * audio control, and system telemetry.
 */

#ifndef REMOTEPC_CORE_H
#define REMOTEPC_CORE_H

#ifdef __cplusplus
extern "C" {
#endif

#ifdef _WIN32
  #ifdef REMOTEPC_EXPORTS
    #define REMOTEPC_API __declspec(dllexport)
  #else
    #define REMOTEPC_API __declspec(dllimport)
  #endif
#else
  #define REMOTEPC_API
#endif

/* Initialize native subsystem (DPI awareness, timer resolution) */
REMOTEPC_API int RemotePC_Init(void);

/* Clean up native subsystem */
REMOTEPC_API void RemotePC_Shutdown(void);

/* Query primary screen dimensions */
REMOTEPC_API void RemotePC_GetScreenSize(int* width, int* height);

/* Fast GDI screen capture into a 32-bit BGRA buffer.
   buf must be pre-allocated to at least width * height * 4 bytes.
   Returns 1 on success, 0 on failure. */
REMOTEPC_API int RemotePC_CaptureScreenBGRA(unsigned char* buf, int max_len, int* out_w, int* out_h);

/* Send relative mouse movement */
REMOTEPC_API int RemotePC_MouseMoveRelative(int dx, int dy);

/* Send absolute mouse click at normalized coordinates (0.0 to 1.0) */
REMOTEPC_API int RemotePC_MouseClickAbsolute(double x_norm, double y_norm, int right_click, int double_click);

/* Send mouse scroll */
REMOTEPC_API int RemotePC_MouseScroll(int lines);

/* Press virtual key code */
REMOTEPC_API int RemotePC_KeyPress(unsigned short vk_code, int key_up);

/* Query system RAM stats */
REMOTEPC_API int RemotePC_GetMemoryStats(unsigned long long* total_bytes, unsigned long long* avail_bytes, int* load_pct);

/* Power and security actions */
REMOTEPC_API int RemotePC_LockWorkstation(void);
REMOTEPC_API int RemotePC_Suspend(int hibernate);

#ifdef __cplusplus
}
#endif

#endif /* REMOTEPC_CORE_H */
