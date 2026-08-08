/// The API client, app state, and the Today screen.
///
/// The HTTP client is a fake, so nothing here touches a network. Widget tests
/// build a real tree and tap real buttons — they run on the Dart VM without a
/// simulator, which is the whole reason this layer is worth testing here.
library;

import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:hydration/api/client.dart';
import 'package:hydration/api/models.dart';
import 'package:hydration/screens/today_screen.dart';
import 'package:hydration/state/app_state.dart';
import 'package:hydration/storage/outbox.dart';

const String kBase = 'http://test.local';

/// Records every request and answers from a canned routing table.
class Recorder {
  final List<http.Request> requests = <http.Request>[];

  MockClient client(
    Map<String, Object> routes, {
    int status = 200,
  }) =>
      MockClient((http.Request request) async {
        requests.add(request);
        final String key = '${request.method} ${request.url.path}';
        final Object? body = routes[key];
        if (body == null) {
          return http.Response(jsonEncode(<String, String>{'detail': 'no route'}), 404);
        }
        if (body is int) {
          return http.Response(jsonEncode(<String, String>{'detail': 'refused'}), body);
        }
        return http.Response(jsonEncode(body), status);
      });
}

Map<String, Object> get _catalogRoute => <String, Object>{
      'GET /api/catalog': <String, Object>{
        'drinks': <Object>[
          <String, Object?>{
            'id': 'water_250',
            'name': 'Water',
            'category': 'water',
            'serving_size_ml': 250,
            'is_alcohol': false,
            'calories': 0.0,
            'caffeine_mg': 0.0,
          },
          <String, Object?>{
            'id': 'latte_350',
            'name': 'Latte',
            'category': 'coffee',
            'serving_size_ml': 350,
            'is_alcohol': false,
            'calories': null,
            'caffeine_mg': null,
          },
          <String, Object?>{
            'id': 'beer_330',
            'name': 'Beer',
            'category': 'beer',
            'serving_size_ml': 330,
            'is_alcohol': true,
            'calories': null,
            'caffeine_mg': null,
          },
        ],
      },
    };

Map<String, Object> todayRoute({Map<String, Object> totals = const <String, Object>{}}) =>
    <String, Object>{
      'GET /api/today': <String, Object?>{
        'date': '2026-08-09',
        'entries': <Object>[],
        'totals': totals,
        'categories': <String, Object>{},
        'water_target_ml': null,
      },
    };

void main() {
  group('ApiClient', () {
    test('sends the bearer token on authenticated calls', () async {
      final Recorder recorder = Recorder();
      final ApiClient api = ApiClient(
        baseUrl: kBase,
        httpClient: recorder.client(todayRoute()),
        token: 'tok-1',
      );

      await api.today();
      expect(recorder.requests.single.headers['Authorization'], 'Bearer tok-1');
    });

    test('sends no Authorization header before linking', () async {
      final Recorder recorder = Recorder();
      final ApiClient api =
          ApiClient(baseUrl: kBase, httpClient: recorder.client(todayRoute()));

      await api.today();
      expect(recorder.requests.single.headers.containsKey('Authorization'), isFalse);
    });

    test('redeeming a code stores the token', () async {
      final Recorder recorder = Recorder();
      final ApiClient api = ApiClient(
        baseUrl: kBase,
        httpClient: recorder.client(<String, Object>{
          'POST /api/link/redeem': <String, Object>{'token': 'tok-9', 'user_id': 'u1'},
        }),
      );

      expect(api.isLinked, isFalse);
      await api.redeem('ABC234');
      expect(api.token, 'tok-9');
      expect(api.isLinked, isTrue);
    });

    test('a 401 is surfaced as unauthorized', () async {
      final Recorder recorder = Recorder();
      final ApiClient api = ApiClient(
        baseUrl: kBase,
        httpClient: recorder.client(<String, Object>{'GET /api/today': 401}),
        token: 'stale',
      );

      await expectLater(
        api.today(),
        throwsA(isA<ApiException>().having((ApiException e) => e.isUnauthorized, 'isUnauthorized', isTrue)),
      );
    });

    test('a 403 is surfaced as forbidden, not as a generic failure', () async {
      // The alcohol gate. The UI needs to tell "locked" from "broken".
      final Recorder recorder = Recorder();
      final ApiClient api = ApiClient(
        baseUrl: kBase,
        httpClient: recorder.client(<String, Object>{'POST /api/entries': 403}),
        token: 'tok',
      );

      await expectLater(
        api.addEntry('beer_330'),
        throwsA(isA<ApiException>().having((ApiException e) => e.isForbidden, 'isForbidden', isTrue)),
      );
    });

    test('null nutrition parses as null rather than zero', () async {
      // The backend leaves unsourced values null on purpose; showing 0 kcal
      // would be inventing the number it declined to invent.
      final Recorder recorder = Recorder();
      final ApiClient api =
          ApiClient(baseUrl: kBase, httpClient: recorder.client(_catalogRoute), token: 't');

      final List<Drink> drinks = await api.catalog();
      final Drink latte = drinks.firstWhere((Drink d) => d.id == 'latte_350');
      expect(latte.calories, isNull);
      expect(latte.hasNutrition, isFalse);
    });

    test('sync posts the events and reports refusals', () async {
      final Recorder recorder = Recorder();
      final ApiClient api = ApiClient(
        baseUrl: kBase,
        httpClient: recorder.client(<String, Object>{
          'POST /api/sync': <String, Object>{
            'applied': 1,
            'refused': <String>['beer-entry'],
            'day_totals': <String, Object>{},
          },
        }),
        token: 't',
      );

      final SyncResult result = await api.sync(<OutboxEvent>[
        const OutboxEvent.add(id: 'e1', drinkId: 'water_250', quantity: 1, loggedAt: null),
      ]);

      expect(result.applied, 1);
      expect(result.refused, <String>['beer-entry']);
      expect(recorder.requests.single.body, contains('water_250'));
    });
  });

  group('AppState', () {
    test('a tap updates the count before the network does', () async {
      // A tracker that spins for a second per tap does not get used.
      final Recorder recorder = Recorder();
      final AppState state = AppState(
        api: ApiClient(baseUrl: kBase, httpClient: recorder.client(<String, Object>{}), token: 't'),
        outbox: Outbox(),
      );

      await state.log('water_250');
      expect(state.totals['water_250'], 1.0);
    });

    test('an undo takes the count back down', () async {
      final Recorder recorder = Recorder();
      final AppState state = AppState(
        api: ApiClient(baseUrl: kBase, httpClient: recorder.client(<String, Object>{}), token: 't'),
        outbox: Outbox(),
      );

      final String id = await state.log('water_250');
      await state.undo(id, 'water_250');
      expect(state.totals.containsKey('water_250'), isFalse);
    });

    test('a failed sync keeps the events queued', () async {
      // Losing a day's drinks to one bad response would be far worse than a retry.
      final Recorder recorder = Recorder();
      final AppState state = AppState(
        api: ApiClient(
          baseUrl: kBase,
          httpClient: recorder.client(<String, Object>{'POST /api/sync': 500}),
          token: 't',
        ),
        outbox: Outbox(),
      );

      await state.log('water_250');
      await state.flush();
      expect(state.pendingCount, greaterThan(0));
    });

    test('a 401 during sync sends the app back to linking', () async {
      final Recorder recorder = Recorder();
      final AppState state = AppState(
        api: ApiClient(
          baseUrl: kBase,
          httpClient: recorder.client(<String, Object>{'POST /api/sync': 401}),
          token: 'stale',
        ),
        outbox: Outbox(),
      );

      await state.log('water_250');
      await state.flush();
      expect(state.status, AppStatus.needsLink);
    });

    test('alcohol is hidden from the catalog until the age check passes', () async {
      final Recorder recorder = Recorder();
      final AppState state = AppState(
        api: ApiClient(
          baseUrl: kBase,
          httpClient: recorder.client(<String, Object>{...todayRoute(), ..._catalogRoute}),
          token: 't',
        ),
      );
      await state.refresh();

      expect(
        state.visibleCatalog(alcoholUnlocked: false).map((Drink d) => d.id),
        isNot(contains('beer_330')),
      );
      expect(
        state.visibleCatalog(alcoholUnlocked: true).map((Drink d) => d.id),
        contains('beer_330'),
      );
    });
  });

  group('TodayScreen', () {
    Future<AppState> readyState(WidgetTester tester, Recorder recorder) async {
      final AppState state = AppState(
        api: ApiClient(
          baseUrl: kBase,
          httpClient: recorder.client(<String, Object>{...todayRoute(), ..._catalogRoute}),
          token: 't',
        ),
      );
      await state.refresh();
      return state;
    }

    testWidgets('shows an empty day', (WidgetTester tester) async {
      final AppState state = await readyState(tester, Recorder());
      await tester.pumpWidget(MaterialApp(home: TodayScreen(state: state)));

      expect(find.byKey(const Key('empty-today')), findsOneWidget);
    });

    testWidgets('tapping a drink shows it immediately', (WidgetTester tester) async {
      final AppState state = await readyState(tester, Recorder());
      await tester.pumpWidget(MaterialApp(home: TodayScreen(state: state)));

      await tester.tap(find.byKey(const Key('add-water_250')));
      await tester.pump();

      expect(find.byKey(const Key('count-water_250')), findsOneWidget);
      expect(find.text('1'), findsOneWidget);
    });

    testWidgets('two taps count as two', (WidgetTester tester) async {
      final AppState state = await readyState(tester, Recorder());
      await tester.pumpWidget(MaterialApp(home: TodayScreen(state: state)));

      await tester.tap(find.byKey(const Key('add-water_250')));
      await tester.pump();
      await tester.tap(find.byKey(const Key('add-water_250')));
      await tester.pump();

      expect(find.text('2'), findsOneWidget);
    });

    testWidgets('an undo affordance appears after a tap', (WidgetTester tester) async {
      final AppState state = await readyState(tester, Recorder());
      await tester.pumpWidget(MaterialApp(home: TodayScreen(state: state)));

      expect(find.byKey(const Key('undo-button')), findsNothing);
      await tester.tap(find.byKey(const Key('add-water_250')));
      await tester.pumpAndSettle();

      expect(find.byKey(const Key('undo-button')), findsOneWidget);
    });

    testWidgets('undo removes the drink again', (WidgetTester tester) async {
      final AppState state = await readyState(tester, Recorder());
      await tester.pumpWidget(MaterialApp(home: TodayScreen(state: state)));

      await tester.tap(find.byKey(const Key('add-water_250')));
      // pumpAndSettle, not pump: Scaffold animates the FAB in, so on the first
      // frame it is scaled to nothing and a tap hit-tests straight past it.
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('undo-button')));
      await tester.pumpAndSettle();

      expect(find.byKey(const Key('count-water_250')), findsNothing);
    });

    testWidgets('alcohol is not offered while locked', (WidgetTester tester) async {
      final AppState state = await readyState(tester, Recorder());
      await tester.pumpWidget(MaterialApp(home: TodayScreen(state: state)));

      expect(find.byKey(const Key('add-water_250')), findsOneWidget);
      expect(find.byKey(const Key('add-beer_330')), findsNothing);
    });

    testWidgets('alcohol appears once unlocked', (WidgetTester tester) async {
      final AppState state = await readyState(tester, Recorder());
      await tester.pumpWidget(
        MaterialApp(home: TodayScreen(state: state, alcoholUnlocked: true)),
      );

      expect(find.byKey(const Key('add-beer_330')), findsOneWidget);
    });

    testWidgets('unsent taps are surfaced rather than hidden', (WidgetTester tester) async {
      final Recorder recorder = Recorder();
      final AppState state = AppState(
        api: ApiClient(
          baseUrl: kBase,
          httpClient: recorder.client(<String, Object>{
            ...todayRoute(),
            ..._catalogRoute,
            'POST /api/sync': 500,
          }),
          token: 't',
        ),
      );
      await state.refresh();
      await tester.pumpWidget(MaterialApp(home: TodayScreen(state: state)));

      await tester.tap(find.byKey(const Key('add-water_250')));
      await tester.pump();
      await state.flush();
      await tester.pump();

      expect(find.byKey(const Key('pending-badge')), findsOneWidget);
    });
  });
}
