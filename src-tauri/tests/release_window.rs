const LIB_SOURCE: &str = include_str!("../src/lib.rs");

#[test]
fn manual_release_window_uses_the_packaged_frontend_entrypoint() {
    assert!(
        LIB_SOURCE.contains("WebviewUrl::App") && LIB_SOURCE.contains("index.html"),
        "manual window creation must use the packaged frontend instead of the development server"
    );
}
