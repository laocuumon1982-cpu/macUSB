import Foundation
import Security

enum HelperConnectionSecurityPolicy {
    static let trustVerificationFailureMarker = "macusb_helper_trust_verification_failed"

    #if DEBUG
    static let expectedHelperBundleIdentifier = "com.kruszoneq.macusb.helper.debug"
    #else
    static let expectedHelperBundleIdentifier = "com.kruszoneq.macusb.helper"
    #endif

    // Ventura/Intel rebuild: the original build pinned the author's Developer ID team.
    // A self-built copy is signed with a different identity, so the requirement is derived
    // from this app's own signature at runtime:
    //  - signed with an Apple-issued certificate (team ID present): same team + helper identifier
    //  - ad-hoc / self-signed (no team ID): helper identifier + exact cdhash of the helper
    //    binary embedded in this app bundle (Contents/Library/Helpers/macUSBHelper)
    nonisolated static let trustedHelperRequirement: String = makeTrustedHelperRequirement()

    nonisolated private static func makeTrustedHelperRequirement() -> String {
        if let team = currentProcessTeamIdentifier() {
            return "anchor apple generic and certificate leaf[subject.OU] = \"\(team)\" and identifier \"\(expectedHelperBundleIdentifier)\""
        }
        let helperURL = Bundle.main.bundleURL
            .appendingPathComponent("Contents/Library/Helpers/macUSBHelper", isDirectory: false)
        if let cdhash = cdHashHex(of: helperURL) {
            return "identifier \"\(expectedHelperBundleIdentifier)\" and cdhash H\"\(cdhash)\""
        }
        return "identifier \"\(expectedHelperBundleIdentifier)\""
    }

    nonisolated private static func signingInformation(of staticCode: SecStaticCode) -> [String: Any]? {
        var info: CFDictionary?
        let flags = SecCSFlags(rawValue: kSecCSSigningInformation)
        guard SecCodeCopySigningInformation(staticCode, flags, &info) == errSecSuccess,
              let dictionary = info as? [String: Any] else { return nil }
        return dictionary
    }

    nonisolated private static func currentProcessTeamIdentifier() -> String? {
        var code: SecCode?
        guard SecCodeCopySelf(SecCSFlags(), &code) == errSecSuccess, let code else { return nil }
        var staticCode: SecStaticCode?
        guard SecCodeCopyStaticCode(code, SecCSFlags(), &staticCode) == errSecSuccess,
              let staticCode else { return nil }
        guard let team = signingInformation(of: staticCode)?[kSecCodeInfoTeamIdentifier as String] as? String,
              !team.isEmpty else { return nil }
        return team
    }

    nonisolated private static func cdHashHex(of url: URL) -> String? {
        var staticCode: SecStaticCode?
        guard SecStaticCodeCreateWithPath(url as CFURL, SecCSFlags(), &staticCode) == errSecSuccess,
              let staticCode,
              let hash = signingInformation(of: staticCode)?[kSecCodeInfoUnique as String] as? Data
        else { return nil }
        return hash.map { String(format: "%02x", $0) }.joined()
    }

    static var localizedFailureTitle: String {
        String(localized: "app.helper.trust.failure.title", table: "App")
    }

    static var localizedFailureMessage: String {
        String(localized: "app.helper.trust.failure.message", table: "App")
    }

    static func configure(_ connection: NSXPCConnection, machServiceName: String) {
        AppLogging.info(
            "Configuring XPC helper code-signing requirement: " +
            "machService=\(machServiceName), expectedHelperBundleID=\(expectedHelperBundleIdentifier).",
            stage: .helper
        )

        AppLogging.info(
            "Wymaganie podpisu helpera: \(trustedHelperRequirement)",
            category: "HelperService"
        )
        connection.setCodeSigningRequirement(trustedHelperRequirement)

        AppLogging.info(
            "XPC helper code-signing requirement configured: machService=\(machServiceName), status=OK.",
            stage: .helper
        )
    }

    static func isCodeSigningRequirementFailure(_ error: Error) -> Bool {
        var currentError: NSError? = error as NSError
        while let nsError = currentError {
            if nsError.domain == NSCocoaErrorDomain,
               nsError.code == NSXPCConnectionCodeSigningRequirementFailure {
                return true
            }
            currentError = nsError.userInfo[NSUnderlyingErrorKey] as? NSError
        }
        return false
    }

    static func isTrustVerificationFailureMessage(_ message: String) -> Bool {
        message.contains(trustVerificationFailureMarker)
    }

    static func diagnosticSummary(for error: Error) -> String {
        let nsError = error as NSError
        var details = [
            "domain=\(nsError.domain)",
            "code=\(nsError.code)"
        ]

        if let debugDescription = nsError.userInfo["NSDebugDescription"] as? String,
           !debugDescription.isEmpty {
            details.append("debug=\(debugDescription)")
        }

        if let underlyingError = nsError.userInfo[NSUnderlyingErrorKey] as? NSError {
            details.append("underlying=\(underlyingError.domain):\(underlyingError.code)")
        }

        return details.joined(separator: ", ")
    }

    static func diagnosticFailureDescription(for error: Error) -> String {
        "\(localizedFailureMessage) [\(trustVerificationFailureMarker), \(diagnosticSummary(for: error))]"
    }
}
