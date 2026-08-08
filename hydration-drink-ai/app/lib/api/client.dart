/// HTTP client for the hydration backend.
///
/// Thin on purpose: it speaks the REST API and returns typed models, and holds
/// no opinions about screens. The `http.Client` is injected so tests drive it
/// with a fake rather than a live server.
library;

import 'dart:convert';

import 'package:http/http.dart' as http;

import 'models.dart';

/// A request the backend refused, with enough detail to show a user.
class ApiException implements Exception {
  ApiException(this.statusCode, this.detail);

  final int statusCode;
  final String detail;

  /// The token is gone or was revoked; the app should return to linking.
  bool get isUnauthorized => statusCode == 401;

  /// The action is locked rather than broken — the alcohol age gate.
  bool get isForbidden => statusCode == 403;

  @override
  String toString() => 'ApiException($statusCode): $detail';
}

/// Talks to the hydration backend.
class ApiClient {
  ApiClient({required this.baseUrl, http.Client? httpClient, this.token})
      : _http = httpClient ?? http.Client();

  final String baseUrl;
  final http.Client _http;

  /// The bearer token, or null when the app is not linked yet.
  String? token;

  bool get isLinked => token != null;

  Map<String, String> get _headers => <String, String>{
        'Content-Type': 'application/json',
        if (token != null) 'Authorization': 'Bearer $token',
      };

  Uri _uri(String path, [Map<String, String>? query]) =>
      Uri.parse('$baseUrl$path').replace(queryParameters: query);

  Map<String, dynamic> _decode(http.Response response) {
    if (response.statusCode >= 400) {
      String detail = response.body;
      try {
        final Object? body = jsonDecode(response.body);
        if (body is Map && body['detail'] != null) {
          detail = body['detail'].toString();
        }
      } on FormatException {
        // Not JSON; the raw body is the best detail available.
      }
      throw ApiException(response.statusCode, detail);
    }
    if (response.body.isEmpty) return <String, dynamic>{};
    return jsonDecode(response.body) as Map<String, dynamic>;
  }

  /// Exchange a bot link code for a token, and remember it.
  Future<String> redeem(String code) async {
    final Map<String, dynamic> body = _decode(
      await _http.post(
        _uri('/api/link/redeem'),
        headers: <String, String>{'Content-Type': 'application/json'},
        body: jsonEncode(<String, String>{'code': code}),
      ),
    );
    token = body['token'] as String;
    return token!;
  }

  /// Today's entries and totals.
  Future<Today> today() async =>
      Today.fromJson(_decode(await _http.get(_uri('/api/today'), headers: _headers)));

  /// The drink catalog.
  Future<List<Drink>> catalog() async {
    final Map<String, dynamic> body =
        _decode(await _http.get(_uri('/api/catalog'), headers: _headers));
    return (body['drinks'] as List<dynamic>)
        .map((Object? d) => Drink.fromJson(d! as Map<String, dynamic>))
        .toList();
  }

  /// Log a drink from the app UI. Returns the new entry's id.
  Future<String> addEntry(String drinkId, {double quantity = 1}) async {
    final Map<String, dynamic> body = _decode(
      await _http.post(
        _uri('/api/entries'),
        headers: _headers,
        body: jsonEncode(<String, dynamic>{'drink_id': drinkId, 'quantity': quantity}),
      ),
    );
    return body['id'] as String;
  }

  /// Remove an entry. The backend tombstones it rather than deleting.
  Future<void> removeEntry(String entryId) async {
    _decode(await _http.delete(_uri('/api/entries/$entryId'), headers: _headers));
  }

  /// Push queued events. Safe to call with a batch that was already sent.
  Future<SyncResult> sync(List<OutboxEvent> events) async {
    final Map<String, dynamic> body = _decode(
      await _http.post(
        _uri('/api/sync'),
        headers: _headers,
        body: jsonEncode(<String, dynamic>{
          'events': events.map((OutboxEvent e) => e.toJson()).toList(),
        }),
      ),
    );
    return SyncResult(
      applied: body['applied'] as int,
      refused: (body['refused'] as List<dynamic>).cast<String>(),
    );
  }

  /// Per-day category totals.
  Future<List<Map<String, dynamic>>> history({int days = 7}) async {
    final Map<String, dynamic> body = _decode(
      await _http.get(
        _uri('/api/history', <String, String>{'days': '$days'}),
        headers: _headers,
      ),
    );
    return (body['days'] as List<dynamic>).cast<Map<String, dynamic>>();
  }

  /// Current settings.
  Future<Map<String, dynamic>> settings() async =>
      _decode(await _http.get(_uri('/api/settings'), headers: _headers));

  /// Update settings. Omitted keys are left alone by the backend.
  Future<void> updateSettings(Map<String, dynamic> changes) async {
    _decode(
      await _http.put(_uri('/api/settings'), headers: _headers, body: jsonEncode(changes)),
    );
  }

  /// Run the self-declared age check. Not verification, and never shown as such.
  Future<bool> ageCheck({required String country, required int age}) async {
    final Map<String, dynamic> body = _decode(
      await _http.post(
        _uri('/api/profile/age-check'),
        headers: _headers,
        body: jsonEncode(<String, dynamic>{'country': country, 'age': age}),
      ),
    );
    return body['alcohol_unlocked'] as bool;
  }
}

/// What a sync call did.
class SyncResult {
  const SyncResult({required this.applied, required this.refused});

  final int applied;

  /// Entry ids the backend would not accept — currently only alcohol before
  /// the age check. Refused per entry, so one drink cannot block the batch.
  final List<String> refused;
}
