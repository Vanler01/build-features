/// App entry point.
library;

import 'package:flutter/material.dart';

import 'api/client.dart';
import 'screens/today_screen.dart';
import 'state/app_state.dart';

/// The backend base URL. Overridden at build time with --dart-define.
const String kBaseUrl = String.fromEnvironment(
  'HYDRATION_API',
  defaultValue: 'http://localhost:8000',
);

void main() {
  runApp(HydrationApp(state: AppState(api: ApiClient(baseUrl: kBaseUrl))));
}

/// Root widget.
class HydrationApp extends StatelessWidget {
  const HydrationApp({required this.state, super.key});

  final AppState state;

  @override
  Widget build(BuildContext context) => MaterialApp(
        title: 'Hydration',
        theme: ThemeData(colorSchemeSeed: Colors.teal, useMaterial3: true),
        home: TodayScreen(state: state),
      );
}
