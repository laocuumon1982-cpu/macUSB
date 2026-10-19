import Foundation
import Security
import os.log

enum HelperConnectionSecurityPolicy {

    #if DEBUG
    static let expectedClientBundleIdentifier = "com.kruszoneq.macUSB.debug"
    #else
    static let expectedClientBundleIdentifier = "com.kruszoneq.macUSB"
    #endif

    // Ventura/Intel rebuild: derive the trusted client requirement from this helper's own
    // signature instead of the original author's hard-coded team ID.
    //  - Apple-issued certificate (team ID present): same team + app identifier
    //  - ad-hoc / self-signed: app identifier + exact cdhash of the enclosing macUSB.app
    static let trustedClientRequirement: String = makeTrustedClientRequirement()

    private static func makeTrustedClientRequirement() -> String {
        if let team = currentProcessTeamIdentifier() {
            return "anchor apple generic and certificate leaf[subject.OU] = \"\(team)\" and identifier \"\(expectedClientBundleIdentifier)\""
        }
        if let appURL = enclosingAppBundleURL(), let cdhash = cdHashHex(of: appURL) {
            return "identifier \"\(expectedClientBundleIdentifier)\" and cdhash H\"\(cdhash)\""
        }
        return "identifier \"\(expectedClientBundleIdentifier)\""
    }

    private static func signingInformation(of staticCode: SecStaticCode) -> [String: Any]? {
        var info: CFDictionary?
        let flags = SecCSFlags(rawValue: kSecCSSigningInformation)
        guard SecCodeCopySigningInformation(staticCode, flags, &info) == errSecSuccess,
              let dictionary = info as? [String: Any] else { return nil }
        return dictionary
    }

    private static func currentProcessStaticCode() -> SecStaticCode? {
        var code: SecCode?
        guard SecCodeCopySelf(SecCSFlags(), &code) == errSecSuccess, let code else { return nil }
        var staticCode: SecStaticCode?
        guard SecCodeCopyStaticCode(code, SecCSFlags(), &staticCode) == errSecSuccess else { return nil }
        return staticCode
    }

    private static func currentProcessTeamIdentifier() -> String? {
        guard let staticCode = currentProcessStaticCode(),
              let team = signingInformation(of: staticCode)?[kSecCodeInfoTeamIdentifier as String] as? String,
              !team.isEmpty else { return nil }
        return team
    }

    private static func enclosingAppBundleURL() -> URL? {
        guard let staticCode = currentProcessStaticCode() else { return nil }
        var pathURL: CFURL?
        guard SecCodeCopyPath(staticCode, SecCSFlags(), &pathURL) == errSecSuccess,
              let executableURL = (pathURL as URL?)?.resolvingSymlinksInPath() else { return nil }
        var current = executableURL.deletingLastPathComponent()
        while current.path != "/" {
            if current.pathExtension == "app" { return current }
            current.deleteLastPathComponent()
        }
        return nil
    }

    private static func cdHashHex(of url: URL) -> String? {
        var staticCode: SecStaticCode?
        guard SecStaticCodeCreateWithPath(url as CFURL, SecCSFlags(), &staticCode) == errSecSuccess,
              let staticCode,
              let hash = signingInformation(of: staticCode)?[kSecCodeInfoUnique as String] as? Data
        else { return nil }
        return hash.map { String(format: "%02x", $0) }.joined()
    }

    private static let trustLog = OSLog(subsystem: "com.kruszoneq.macusb.helper", category: "XPCTrust")

    static func configure(_ listener: NSXPCListener, machServiceName: String) {
        HelperDiagnosticLogging.info(
            "Configuring XPC client trust requirement: machService=\(machServiceName) expectedClientBundleID=\(expectedClientBundleIdentifier)",
            stage: .helper,
            log: trustLog
        )

        os_log(
            "XPC client requirement: %{public}@",
            log: trustLog,
            type: .default,
            trustedClientRequirement
        )
        listener.setConnectionCodeSigningRequirement(trustedClientRequirement)

        HelperDiagnosticLogging.info(
            "XPC client trust requirement configured: machService=\(machServiceName) status=OK",
            stage: .helper,
            log: trustLog
        )
    }

    static func logAcceptedConnection(_ connection: NSXPCConnection) {
        HelperDiagnosticLogging.info(
            "Accepted XPC connection prevalidated by code signing requirement: pid=\(connection.processIdentifier) euid=\(connection.effectiveUserIdentifier) expectedClientBundleID=\(expectedClientBundleIdentifier)",
            stage: .helper,
            log: trustLog
        )
    }
}
