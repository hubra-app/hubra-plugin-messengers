import { registerPlugin } from '@hubra/plugin-sdk'
import { IconMessages } from '@tabler/icons-react'
import { MessengersScreen } from './MessengersScreen'
import translations from './translations.json'

registerPlugin({
  id: 'messengers',
  routes: [
    { path: 'messengers', module: 'messengers', perm: 'messengers.channels.update', component: MessengersScreen },
  ],
  // The nav entry in hubra_messengers/__init__.py names this icon.
  icons: { messages: IconMessages },
  translations,
})
